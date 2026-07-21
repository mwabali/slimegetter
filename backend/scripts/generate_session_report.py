"""Generate one read-only EAT session report from the journal database."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.application.session_reports import SessionBounds, build_session_report, write_session_report
from app.infrastructure.persistence.database import SessionLocal


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="UTC ISO timestamp")
    parser.add_argument("--end", required=True, help="UTC ISO timestamp")
    parser.add_argument("--window-key", required=True)
    parser.add_argument("--output-root", default=str(ROOT / "reports" / "session"))
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start.replace("Z", "+00:00")).astimezone(UTC)
    end = datetime.fromisoformat(args.end.replace("Z", "+00:00")).astimezone(UTC)
    with SessionLocal() as session:
        report = build_session_report(session, SessionBounds(args.window_key, start, end))
    paths = write_session_report(report, Path(args.output_root))
    print({"json": str(paths[0]), "markdown": str(paths[1])})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
