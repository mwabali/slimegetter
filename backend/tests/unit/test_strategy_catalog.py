from collections import Counter

from app.strategies.catalog import CATALOG


def test_catalog_has_1800_unique_research_candidates() -> None:
    assert len(CATALOG) == 1800
    assert len({spec.version for spec in CATALOG}) == 1800
    assert {spec.status for spec in CATALOG} == {"RESEARCH"}


def test_catalog_has_120_candidates_per_family() -> None:
    assert set(Counter(spec.family for spec in CATALOG).values()) == {120}
