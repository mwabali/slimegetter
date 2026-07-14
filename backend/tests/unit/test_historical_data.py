import json
from datetime import UTC, datetime
from decimal import Decimal

from app.research.historical_data import OandaCandleClient, inspect_dataset


class _Response:
    def __init__(self, payload: dict): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_): return None
    def read(self): return json.dumps(self.payload).encode()


def test_oanda_client_requests_bid_ask_and_deduplicates_boundaries() -> None:
    raw = {"complete": True, "time": "2023-01-02T00:00:00.000000000Z", "volume": 2,
           "bid": {"o": "1800", "h": "1802", "l": "1799", "c": "1801"},
           "ask": {"o": "1800.2", "h": "1802.2", "l": "1799.2", "c": "1801.2"}}
    requests = []
    def opener(request, timeout):
        requests.append(request)
        return _Response({"candles": [raw]})
    rows = OandaCandleClient("secret", opener=opener).fetch(
        "XAU_USD", datetime(2023, 1, 1, tzinfo=UTC), datetime(2023, 2, 1, tzinfo=UTC))
    assert len(rows) == 1
    assert len(requests) == 3
    assert all("price=BA" in request.full_url for request in requests)
    assert all(request.headers["Authorization"] == "Bearer secret" for request in requests)


def test_dataset_qa_rejects_less_than_three_calendar_years() -> None:
    raw = {"complete": True, "time": "2023-01-02T00:00:00Z", "volume": 2,
           "bid": {"o": "1800", "h": "1802", "l": "1799", "c": "1801"},
           "ask": {"o": "1800.2", "h": "1802.2", "l": "1799.2", "c": "1801.2"}}
    client = OandaCandleClient("secret", opener=lambda *_args, **_kwargs: _Response({"candles": [raw]}))
    rows = client.fetch("XAU_USD", datetime(2023, 1, 1, tzinfo=UTC), datetime(2023, 1, 2, tzinfo=UTC))
    manifest = inspect_dataset(rows)
    assert manifest.median_close_spread == Decimal("0.2")
    assert not manifest.suitable_for_final_validation
