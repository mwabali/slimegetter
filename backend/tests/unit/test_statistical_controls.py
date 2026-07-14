from app.research.statistical_controls import (
    HypothesisResult,
    benjamini_hochberg,
    newey_west_mean_p_value,
    select_uncorrelated,
)


def test_benjamini_hochberg_does_not_treat_raw_point_zero_five_as_enough() -> None:
    rows = tuple(HypothesisResult(f"s{i}", value) for i, value in enumerate((0.0001, 0.001, 0.02, 0.041, 0.20), 1))
    by_version = {row.version: row for row in benjamini_hochberg(rows, q=0.05)}
    assert by_version["s1"].passes_fdr
    assert by_version["s2"].passes_fdr
    assert not by_version["s4"].passes_fdr


def test_correlation_control_keeps_ranked_leader() -> None:
    decisions = dict(select_uncorrelated((
        ("leader", (1.0, -1.0, 2.0, -2.0)),
        ("clone", (2.0, -2.0, 4.0, -4.0)),
        ("different", (1.0, 1.0, -1.0, -1.0)),
    )))
    assert decisions["leader"] is None
    assert decisions["clone"] == "leader"
    assert decisions["different"] is None


def test_hac_test_requires_positive_daily_edge() -> None:
    assert newey_west_mean_p_value(tuple([1.0, -1.0] * 100)) > 0.4
    assert newey_west_mean_p_value(tuple([1.0, 0.5] * 100)) < 0.01
