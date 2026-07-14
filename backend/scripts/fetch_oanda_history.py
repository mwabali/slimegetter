import json
import os
from datetime import UTC, datetime
from pathlib import Path

from app.research.historical_data import OandaCandleClient, write_dataset


def run() -> None:
    token = os.environ.get("OANDA_API_TOKEN", "")
    if not token:
        raise SystemExit("Set OANDA_API_TOKEN in the process environment; never put it in source control")
    start = datetime.fromisoformat(os.environ.get("OANDA_HISTORY_START", "2020-01-01")).replace(tzinfo=UTC)
    end = datetime.now(UTC)
    output = Path(os.environ.get("OANDA_HISTORY_PATH", "data/research/xau_usd_m5_oanda.csv"))
    candles = OandaCandleClient(token=token).fetch("XAU_USD", start, end)
    manifest = write_dataset(output, candles)
    manifest_path = output.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest.model_dump(mode="json"), indent=2), encoding="utf-8")
    print(f"rows={manifest.rows} years={manifest.calendar_years} suitable={manifest.suitable_for_final_validation}")


if __name__ == "__main__":
    run()
