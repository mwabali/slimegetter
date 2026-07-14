# XAUUSD Mission Control runtime readiness

## Current authorized mode

- `READ_ONLY_SHADOW_MODE`
- MT5 demo account only
- Execution disabled
- Kill switch active
- Continuous agent, forward-strategy, and paper-ledger workers
- No live-money execution path is authorized

## Evidence required before guarded demo orders

1. Annie must provide verified event coverage; unknown calendar state blocks trading.
2. Mikasa calibration must be supported by frozen historical and forward evidence.
3. A strategy must survive development, FDR, stability, correlation, untouched holdout, and forward paper gates.
4. At least 30 forward paper trades are required; this count alone does not guarantee promotion.
5. Commander Erwin must approve both the original and broker-sized proposal.
6. The MT5 terminal must identify the connected account as demo.
7. The durable execution claim must be created before order submission.
8. Any ambiguous broker response enters `UNKNOWN_RECONCILE` and cannot retry automatically.
9. Demo activation requires explicit configuration gates; live mode remains refused.

## Verification

Run from `backend` while the stack is active:

```powershell
python scripts/verify_shadow_stack.py
pytest tests -q
```

The verifier fails unless execution is disabled, the kill switch is active, MT5 and all workers are healthy, the latest replay is ordered and complete, chart data is available, and account orders sent remains zero.

## Strategy research status

The frozen development screen contains 1,800 candidates across 15 families, of which 1,687 produced empirically distinct behavior. Twelve passed base walk-forward gates; none passed the locked false-discovery control. The untouched holdout therefore remains sealed and no strategy is approved.

## Strategy coverage and reserve

The strategy library now has a deterministic coverage plan with 30 distinct
research candidates for each of 12 market situations and a separate reserve
pool of 100 candidates. Rejected candidates do not count toward operational
coverage; reserve candidates are available as replacements. The strategy
shadow worker observes the core and reserve cohort in forward-only mode. This
does not promote strategies or grant MT5 execution authority.

The coverage view is available at `/api/v1/strategies/coverage` and reports
registered, eligible, shadow, and replacement counts for every situation.

## Mikasa advisory comparison

Mikasa is a continuous market-intelligence and market-memory agent. She emits
the legacy threshold result only for comparison, but never vetoes a proposal.
Spread, liquidity, volatility, momentum, session and outcomes from similar
past entries become evidence that adjusts confidence and proposed sizing.
Mikasa reports weak or incomplete data explicitly and continues observing.
Erwin is the sole deterministic risk authority. This behavior remains
shadow-only until forward evidence supports changing demo behavior.

## Erwin calculated-risk command

Erwin distinguishes opportunity imperfections from account-survival stops.
Wide spreads, non-preferred sessions, lower reward/risk and oversized proposals
produce an explicit reduced-size commitment rather than an automatic retreat.
Invalid protective levels, exhausted margin/exposure/trade capacity, and the
daily or weekly survival stop still reject the campaign. Every accepted warning,
risk posture and size multiplier is journaled for later Armin evaluation.
