from app.strategies.validation_policy import LOCKED_POLICY


def test_policy_reserves_untouched_holdout_and_never_auto_promotes() -> None:
    assert LOCKED_POLICY.development_fraction + LOCKED_POLICY.walk_forward_fraction + LOCKED_POLICY.untouched_holdout_fraction == 1
    assert LOCKED_POLICY.untouched_holdout_fraction > 0
    assert LOCKED_POLICY.human_promotion_required
    assert not LOCKED_POLICY.automatic_live_promotion
