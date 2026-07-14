import os
from pathlib import Path

from app.research.histdata_pipeline import build_histdata_dataset


if __name__ == "__main__":
    source = Path(os.environ.get("HISTDATA_ARCHIVE_DIR", "work/histdata"))
    output = Path(os.environ.get("HISTDATA_OUTPUT_DIR", "work/research_dataset"))
    result = build_histdata_dataset(source, output)
    print(f"manifest={result.manifest_path}")
    print(f"m5_rows={result.manifest['m5_rows']} development={result.manifest['development_rows']} untouched_holdout={result.manifest['holdout_rows']}")
