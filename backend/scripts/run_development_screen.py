import os
from pathlib import Path

from app.research.screening_report import run_development_screen
from app.strategies.catalog import CATALOG


if __name__ == "__main__":
    root = Path(os.environ.get("RESEARCH_DATASET_DIR", "work/research_dataset"))
    output = Path(os.environ.get("DEVELOPMENT_SCREEN_REPORT", "work/research_results/development_screen.json"))
    report = run_development_screen(
        CATALOG, root / "xauusd_m5_development_80pct.npz", root / "xauusd_m5_manifest.json", output,
        float(os.environ.get("RESEARCH_SPREAD", "0.30")), float(os.environ.get("RESEARCH_SLIPPAGE", "0.10")),
    )
    print(f"candidates={report['candidate_count']} fdr_stable={report['base_and_fdr_stable_count']} development_survivors={report['after_neighborhood_and_correlation_count']}")
    print(f"report={output}")
