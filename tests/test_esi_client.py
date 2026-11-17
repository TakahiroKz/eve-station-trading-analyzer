"""EsiClient.get_orders: las páginas del libro de órdenes se piden en paralelo pero el resultado
se arma en orden, y una página que falla no se pierde en silencio."""
import threading
import time

import httpx
import pytest

from ingestion.esi_client import EsiClient

REGION = 10000002


def _client(handler, orders_workers):
    client = EsiClient(orders_workers=orders_workers, max_retries=0)
    client._client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://esi.test")
    client.base_url = "https://esi.test"
    return client


def _pages_handler(total_pages, in_flight=None, delay=0.0):
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        if in_flight is not None:
            with in_flight["lock"]:
                in_flight["now"] += 1
                in_flight["max"] = max(in_flight["max"], in_flight["now"])
            time.sleep(delay)
            with in_flight["lock"]:
                in_flight["now"] -= 1
        return httpx.Response(200, json=[{"order_id": page * 1000 + n, "type_id": page} for n in range(2)],
                              headers={"X-Pages": str(total_pages)})
    return handler


def _tracker():
    return {"lock": threading.Lock(), "now": 0, "max": 0}


def test_get_orders_collects_every_page_in_page_order():
    client = _client(_pages_handler(total_pages=12), orders_workers=4)

    orders = client.get_orders(REGION)

    assert [o["type_id"] for o in orders] == [p for p in range(1, 13) for _ in range(2)]
    assert len(orders) == 24


def test_get_orders_requests_pages_concurrently_up_to_the_configured_workers():
    tracker = _tracker()
    client = _client(_pages_handler(total_pages=20, in_flight=tracker, delay=0.05), orders_workers=5)

    client.get_orders(REGION)

    assert 2 <= tracker["max"] <= 5


def test_get_orders_with_one_worker_is_sequential():
    tracker = _tracker()
    client = _client(_pages_handler(total_pages=6, in_flight=tracker, delay=0.01), orders_workers=1)

    orders = client.get_orders(REGION)

    assert tracker["max"] == 1
    assert len(orders) == 12


def test_get_orders_single_page_makes_one_request():
    calls = []

    def handler(request):
        calls.append(request.url.params["page"])
        return httpx.Response(200, json=[{"order_id": 1}], headers={"X-Pages": "1"})

    client = _client(handler, orders_workers=8)

    assert client.get_orders(REGION, type_id=34) == [{"order_id": 1}]
    assert calls == ["1"]


def test_get_orders_sends_the_type_filter_on_every_page():
    seen = []

    def handler(request):
        seen.append((request.url.params["page"], request.url.params.get("type_id"), request.url.params["order_type"]))
        return httpx.Response(200, json=[], headers={"X-Pages": "3"})

    _client(handler, orders_workers=2).get_orders(REGION, order_type="sell", type_id=34)

    assert sorted(seen) == [("1", "34", "sell"), ("2", "34", "sell"), ("3", "34", "sell")]


def test_get_orders_propagates_a_failing_page():
    def handler(request):
        if request.url.params["page"] == "7":
            return httpx.Response(404, json={"error": "gone"})
        return httpx.Response(200, json=[], headers={"X-Pages": "10"})

    with pytest.raises(httpx.HTTPStatusError):
        _client(handler, orders_workers=4).get_orders(REGION)


def test_orders_workers_comes_from_the_environment_and_never_drops_below_one(monkeypatch):
    monkeypatch.setenv("ESI_ORDERS_WORKERS", "12")
    assert EsiClient().orders_workers == 12
    monkeypatch.setenv("ESI_ORDERS_WORKERS", "0")
    assert EsiClient().orders_workers == 1
    monkeypatch.delenv("ESI_ORDERS_WORKERS")
    assert EsiClient().orders_workers == 8
