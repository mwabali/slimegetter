"""Fail-closed end-to-end verification of the local read-only Mission Control stack."""
from __future__ import annotations

import json
from urllib.request import urlopen

BASE = "http://127.0.0.1:8000/api/v1"


def get(path: str):
    with urlopen(f"{BASE}{path}", timeout=20) as response:  # noqa: S310 - fixed localhost target
        return json.load(response)


def main() -> None:
    status = get("/system/status"); account = get("/mt5/account")
    quote = get("/mt5/symbols/xauusd"); chart = get("/mt5/chart/xauusd")
    cycle = get("/cycles/current"); agents = get("/agents/status")
    paper = get("/simulation/positions"); learning = get("/learning")
    assert status["platform_mode"] == "READ_ONLY_SHADOW_MODE"
    assert status["execution_enabled"] is False
    assert status["kill_switch_active"] is True
    assert status["mt5"]["state"] == "HEALTHY"
    for worker in ("shadow_worker", "strategy_shadow_worker", "simulation_worker"):
        assert status[worker]["state"] == "HEALTHY", (worker, status[worker])
    assert account["account_type"] == "DEMO" and account["orders_sent"] == 0
    assert quote["symbol"] == "XAUUSD" and quote["bid"] and quote["ask"]
    assert len(chart["bars"]) >= 30
    assert len(agents) == 6 and {row["name"] for row in agents} == {"ANNIE", "MIKASA", "EREN", "COMMANDER_ERWIN", "ARMIN", "CPT_LEVI"}
    assert cycle and cycle["correlation_id"]
    replay = get(f"/replay/{cycle['correlation_id']}")
    sequences = [row["sequence"] for row in replay]
    assert sequences == sorted(set(sequences)) and len(replay) == cycle["event_count"]
    assert isinstance(paper, list)
    assert isinstance(learning["strategies"], list) and isinstance(learning["paper_strategies"], list)
    print(json.dumps({
        "verified": True, "mode": status["platform_mode"], "orders_sent": account["orders_sent"],
        "cycle": cycle["correlation_id"], "replay_events": len(replay), "chart_bars": len(chart["bars"]),
        "paper_positions": len(paper), "workers": {name: status[name]["state"] for name in ("shadow_worker", "strategy_shadow_worker", "simulation_worker")},
    }, indent=2))


if __name__ == "__main__":
    main()
