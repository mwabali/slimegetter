# Known-Good Reconstruction Record

Date: 2026-07-21
Operator timezone: Africa/Nairobi (EAT)

## Result

`KNOWN_GOOD_RECONSTRUCTED_STATE=TradingBot Master Avenger reference at commit 5aab35d, adapted to the clean SlimeGetter base at commit 3cf4716; exact combined historical commit is unavailable.`

This worktree is a validation baseline only. It is not authorized to submit
orders and it does not inherit the July 20-21 Mutiny changes from the losing
fusion branch.

## Evidence

- The local `TradingBot-project2` clone is at `5aab35d` (`Restore June Flash
  demo with ten position slots`).
- The reference implementation is the MQL5 `StraddleExecutionEA` with the
  Master Avenger configuration family.
- The sanitized reference configuration used by the fusion recorded Thor
  geometry: trigger 3.00, stop 6.00, take profit 9.00, trail 1.00, trail
  threshold 0.50, one bracket, 60-minute expiration, and zero rearm delay.
- The reference CEO-FD configuration documents two EAT operating windows:
  03:00-05:00 and 16:00-22:00. These are recovered configuration values, not
  newly invented trading hours.
- SlimeGetter's public Git history ends at `3cf4716` before the Avenger fusion.
  The Avenger Python bridge, Mutiny authority, and later lifecycle changes
  were all introduced as uncommitted working-tree changes before the July 21
  preservation commit `4af68f3`.
- Repository reflog and unreachable-object inspection found no earlier
  SlimeGetter commit containing the combined Avenger integration.

## Why this is a reconstruction

The source Avenger state and the clean SlimeGetter state are independently
recoverable, but their first combined runtime state was never committed. The
baseline therefore records the two source points and the exact recovered
parameters without silently importing current fusion improvements.

## Validation gate

Before any demo run from this worktree, verify MT5 demo mode, XAUUSD symbol,
terminal permissions, pending-order protection, position management, close
confirmation, reconciliation, database state, and worker singleton behavior.
Use a read-only smoke test first. Do not attach credentials or enable live
execution in this worktree.
