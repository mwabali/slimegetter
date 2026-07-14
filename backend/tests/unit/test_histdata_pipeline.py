from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np

from app.research.histdata_pipeline import build_histdata_dataset


def _archive(path: Path, year: int) -> None:
    rows = []
    for minute in range(10):
        rows.append(f"{year}0102 000{minute}00;100;101;99;100.5;0")
    with ZipFile(path, "w", ZIP_DEFLATED) as target:
        target.writestr(f"DAT_ASCII_XAUUSD_M1_{year}.csv", "\n".join(rows))


def test_build_separates_untouched_holdout(tmp_path: Path) -> None:
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    for year in (2021, 2022, 2023):
        _archive(source / f"xauusd_m1_{year}.zip", year)
    result = build_histdata_dataset(source, output)
    assert result.manifest["years"] == [2021, 2022, 2023]
    assert result.manifest["holdout_opened"] is False
    development = np.load(result.development_path)
    holdout = np.load(result.holdout_path)
    assert len(development["time"]) + len(holdout["time"]) == 6
    assert development["time"].max() < holdout["time"].min()
