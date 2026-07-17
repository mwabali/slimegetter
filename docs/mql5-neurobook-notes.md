# MQL5 NeuroBook Notes

Source: https://www.mql5.com/en/neurobook

## Useful Ideas For Mission Control

- Keep Python as the research and orchestration layer. The book explicitly covers MetaEditor/Python integration, but this project already uses Python well through FastAPI, workers, strategy validation, and the MetaTrader5 Python package.
- Do not feed every possible indicator into a model. The NeuroBook emphasizes input selection, normalization, correlation analysis, and removing weak or redundant features before training. This maps directly to Armin/Mikasa research: build feature screens before adding neural models.
- Use MT5 Strategy Tester as an independent validation tool. It supports real-tick modeling, parameter optimization, forward testing, and multi-threaded/cloud optimization. This should complement, not replace, the current Python backtesting and paper-ledger flow.
- Treat a neural model as a signal producer, not as the risk authority. In this codebase, any future neural model should produce an Eren-style proposal or Mikasa-style confidence adjustment. Commander Erwin must remain the final deterministic gate.
- Require out-of-sample testing before promotion. The book's forward-test section aligns with this repo's existing development/holdout/forward-paper mindset.

## Best Fit Implementation Path

1. Add a feature dataset exporter from MT5 bars and existing indicators.
2. Add correlation and redundancy reports for candidate features.
3. Train models in Python first, with walk-forward and holdout validation.
4. Register approved models as strategy candidates in the existing strategy catalog.
5. Let the model output only directional probability, confidence, or expected move.
6. Keep order sizing, exposure, news lockout, demo verification, and kill switch in existing Python services.

## What Not To Do Yet

- Do not rewrite the platform in MQL5.
- Do not let a neural model call `order_send` directly.
- Do not use Strategy Tester optimization results alone as promotion evidence.
- Do not move live/demo execution out of the guarded worker boundary.

