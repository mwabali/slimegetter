# Known-Good Reconstruction Record

Date: 2026-07-21
Operator timezone: Africa/Nairobi (EAT)

## Result

`KNOWN_GOOD_RECONSTRUCTED_STATE=Sunday-night Avenger/SlimeGetter fusion replayed from the local Codex session transcript on clean SlimeGetter 3cf4716, including the two MT5 broker-compatibility fixes applied before monitoring was added.`

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
  The local Codex session transcript records the complete uncommitted patch
  sequence assembled on Sunday night: settings and `avenger.py`, pending-order
  and OCO gateway support, bracket execution, demo entry wiring, position
  cleanup, and tests.
- The transcript also records two broker-compatibility patches before the
  later monitoring work: fallback from broker-rejected specified expiration to
  GTC, then short MT5-safe comments for cancellation and close requests.
- Repository reflog and unreachable-object inspection found no earlier
  SlimeGetter commit containing the combined Avenger integration, so this
  worktree is an exact patch replay rather than a recovered Git commit.

## Runtime proof

- The transcript records the first live demo bracket being accepted by MT5,
  one leg filling, the opposite pending leg being cancelled, and Pixis closing
  the filled position after the comment fix.
- A fresh Avenger bracket was then submitted. Subsequent overnight monitor
  records show repeated short fills followed by Pixis closes and new bracket
  staging.
- The replay boundary intentionally stops before the later monitor,
  singleton, and Mutiny changes. Those belong to the operational/fusion
  branches, not this early known-good trading baseline.

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
