"""Cola duradera de avisos de Telegram: no duplica, reintenta, descarta lo viejo y no se pisa entre motores."""
import os
import threading
from datetime import datetime, timedelta, timezone

import pytest

from notifications import outbox
from storage.db import get_connection, init_db


@pytest.fixture
def db(monkeypatch, tmp_path):
    path = str(tmp_path / "outbox.db")
    init_db(path)
    monkeypatch.setenv("DB_PATH", path)
    return path


def _rows(path):
    conn = get_connection(path)
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM notification_outbox ORDER BY id")]
    finally:
        conn.close()


def _age(path, minutes):
    conn = get_connection(path)
    old = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    conn.execute("UPDATE notification_outbox SET created_at = ?", (old,))
    conn.commit()
    conn.close()


def test_enqueue_does_not_duplicate_an_identical_pending_message(db):
    assert outbox.enqueue("texto", "ctx") is True
    assert outbox.enqueue("texto", "ctx") is True
    assert outbox.enqueue("otro", "ctx") is True

    assert [r["text"] for r in _rows(db)] == ["texto", "otro"]
    assert outbox.pending_count() == 2


def test_drain_sends_pending_messages_and_removes_them(db):
    outbox.enqueue("uno", "a")
    outbox.enqueue("dos", "b")
    sent = []

    count = outbox.drain(lambda text: sent.append(text) or True)

    assert count == 2
    assert sorted(sent) == ["dos", "uno"]
    assert _rows(db) == []


def test_drain_keeps_a_message_that_fails_again_for_the_next_run(db):
    outbox.enqueue("uno", "a")

    assert outbox.drain(lambda text: False) == 0

    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0]["attempts"] == 1 and rows[0]["claimed_at"] is None and rows[0]["last_error"]
    assert outbox.drain(lambda text: True) == 1  # al siguiente intento sale
    assert _rows(db) == []


def test_drain_treats_an_exception_in_the_sender_as_a_failed_attempt(db):
    outbox.enqueue("uno", "a")

    def boom(text):
        raise RuntimeError("red")

    assert outbox.drain(boom) == 0
    assert len(_rows(db)) == 1


def test_drain_discards_messages_older_than_the_limit(db):
    outbox.enqueue("viejo", "a")
    _age(db, outbox.MAX_AGE_MINUTES + 5)
    sent = []

    assert outbox.drain(lambda text: sent.append(text) or True) == 0

    assert sent == []  # un aviso de hace más de media hora ya no sirve
    assert _rows(db) == []


def test_drain_gives_up_after_the_maximum_attempts(db):
    outbox.enqueue("terco", "a")
    conn = get_connection(db)
    conn.execute("UPDATE notification_outbox SET attempts = ?", (outbox.MAX_ATTEMPTS,))
    conn.commit()
    conn.close()
    sent = []

    outbox.drain(lambda text: sent.append(text) or True)

    assert sent == [] and _rows(db) == []


def test_two_engines_draining_at_once_do_not_send_the_same_message_twice(db):
    outbox.enqueue("unico", "a")
    sent = []
    gate = threading.Barrier(2)

    def send(text):
        sent.append(text)
        return True

    def run():
        gate.wait()
        outbox.drain(send)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sent == ["unico"]


def test_pending_count_and_drain_do_not_create_a_missing_database(monkeypatch, tmp_path):
    path = str(tmp_path / "no_existe.db")
    monkeypatch.setenv("DB_PATH", path)

    assert outbox.pending_count() == 0
    assert outbox.drain(lambda text: True) == 0
    assert not os.path.exists(path)
