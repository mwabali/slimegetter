from app.strategies.catalog import CATALOG
from app.strategies.coverage import DEFAULT_MINIMUM_PER_SITUATION, DEFAULT_RESERVE_POOL_SIZE, SITUATIONS, build_coverage_plan, coverage_status


def test_coverage_plan_has_thirty_per_situation_and_one_hundred_reserve() -> None:
    plan = build_coverage_plan(CATALOG)
    assert len(plan.situations) == len(SITUATIONS)
    assert all(len(bucket.versions) == DEFAULT_MINIMUM_PER_SITUATION for bucket in plan.situations)
    assert len(plan.reserve_versions) == DEFAULT_RESERVE_POOL_SIZE
    assert set(plan.reserve_versions).isdisjoint(plan.planned_versions)


def test_coverage_status_distinguishes_catalog_coverage_from_operational_readiness() -> None:
    plan = build_coverage_plan(CATALOG)
    status = coverage_status(plan, {version: "RESEARCH" for version in plan.planned_versions})
    assert status["coverage_complete"] is True
    assert status["operational_core_complete"] is True
    assert status["reserve_complete"] is True
    assert all(item["registered"] == DEFAULT_MINIMUM_PER_SITUATION for item in status["situations"])


def test_reserve_can_replace_rejected_core_candidates_without_promotion() -> None:
    plan = build_coverage_plan(CATALOG)
    registered = {version: "RESEARCH" for version in plan.planned_versions + plan.reserve_versions}
    for version in plan.situations[2].versions[:5]:
        registered[version] = "REJECTED"
    status = coverage_status(plan, registered)
    assert status["operational_core_complete"] is True
    assert status["reserve_replacements_used"] >= 5
