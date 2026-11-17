"""Envío a Telegram: acotado, con un reintento ante fallos pasajeros y cola duradera si no sale."""
import httpx
import pytest

from notifications import outbox, telegram_bot
from storage.db import get_connection, init_db


@pytest.fixture
def configured(monkeypatch, tmp_path):
    db = str(tmp_path / "bot.db")
    init_db(db)
    monkeypatch.setenv("DB_PATH", db)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:TEST")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(telegram_bot.time, "sleep", lambda s: None)  # sin esperas reales
    return db


def _fake_post(responses, calls):
    """responses: lista de httpx.Response o excepciones, una por intento."""
    def post(url, json=None, timeout=None):
        calls.append({"url": url, "json": json, "timeout": timeout})
        item = responses[len(calls) - 1]
        if isinstance(item, Exception):
            raise item
        return item
    return post


def _resp(status, body=None):
    return httpx.Response(status, json=body or {}, request=httpx.Request("POST", "https://api.telegram.org/x"))


def test_a_successful_send_makes_one_request_with_short_timeouts(configured, monkeypatch):
    calls = []
    monkeypatch.setattr(telegram_bot.httpx, "post", _fake_post([_resp(200, {"ok": True})], calls))

    assert telegram_bot._send_message("hola", "prueba") is True

    assert len(calls) == 1
    assert calls[0]["json"] == {"chat_id": "42", "text": "hola"}
    timeout = calls[0]["timeout"]
    assert (timeout.connect, timeout.read) == (3.0, 5.0)
    assert outbox.pending_count() == 0


def test_a_network_error_is_retried_once_and_can_succeed(configured, monkeypatch):
    calls = []
    monkeypatch.setattr(
        telegram_bot.httpx, "post",
        _fake_post([httpx.ConnectTimeout("lento"), _resp(200, {"ok": True})], calls),
    )

    assert telegram_bot._send_message("hola", "prueba") is True
    assert len(calls) == 2
    assert outbox.pending_count() == 0


def test_a_429_waits_for_retry_after_capped_and_retries(configured, monkeypatch):
    slept = []
    monkeypatch.setattr(telegram_bot.time, "sleep", lambda s: slept.append(s))
    calls = []
    monkeypatch.setattr(
        telegram_bot.httpx, "post",
        _fake_post([_resp(429, {"parameters": {"retry_after": 60}}), _resp(200, {"ok": True})], calls),
    )

    assert telegram_bot._send_message("hola", "prueba") is True
    assert slept == [telegram_bot.MAX_RETRY_WAIT_SECONDS]  # 60 s pedidos, tope de 5 s


def test_persistent_transient_failure_goes_to_the_outbox_after_one_retry(configured, monkeypatch):
    calls = []
    monkeypatch.setattr(
        telegram_bot.httpx, "post",
        _fake_post([httpx.ConnectError("sin red"), _resp(502)], calls),
    )

    assert telegram_bot._send_message("aviso importante", "oportunidad X") is False

    assert len(calls) == 2  # un intento y un solo reintento
    assert outbox.pending_count() == 1
    conn = get_connection(configured)
    row = conn.execute("SELECT text, context FROM notification_outbox").fetchone()
    conn.close()
    assert (row["text"], row["context"]) == ("aviso importante", "oportunidad X")


def test_a_client_error_is_not_retried_nor_queued(configured, monkeypatch):
    calls = []
    monkeypatch.setattr(telegram_bot.httpx, "post", _fake_post([_resp(401, {"ok": False})], calls))

    assert telegram_bot._send_message("hola", "prueba") is False

    assert len(calls) == 1
    assert outbox.pending_count() == 0  # token mal puesto: reintentar no lo arregla


def test_not_configured_does_nothing_and_does_not_queue(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "x.db"))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    def boom(*a, **k):
        raise AssertionError("no debería llamar a Telegram")

    monkeypatch.setattr(telegram_bot.httpx, "post", boom)

    assert telegram_bot._send_message("hola", "prueba") is False
    assert outbox.pending_count() == 0


def test_the_api_base_can_be_overridden_for_tests(configured, monkeypatch):
    calls = []
    monkeypatch.setenv("TELEGRAM_API_BASE", "http://10.255.255.1:9/")
    monkeypatch.setattr(telegram_bot.httpx, "post", _fake_post([_resp(200)], calls))

    telegram_bot._send_message("hola", "prueba")

    assert calls[0]["url"].startswith("http://10.255.255.1:9/bot123:TEST/")
