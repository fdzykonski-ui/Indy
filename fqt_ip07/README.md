# FQT IP07 — Execution-neutral signal-generation correctness harness

## Purpose

IP07 addresses `DEF-LOOKAHEAD-001`: the frozen champion produces 663 trades in
its ordinary deterministic portfolio backtest, while Freqtrade's generic
lookahead helper completes only one trade after changing portfolio execution
state.  The helper therefore emits no valid verdict.

IP07 separates two questions:

1. **Are indicator, entry-signal, dataframe exit-signal and tag outputs
   future-causal?**
2. **Is the complete champion portfolio/execution callback path valid under the
   generic helper?**

The diagnostic class can answer the first question only.  It inherits the
frozen V10/V14 alpha callbacks unchanged and neutralizes execution-only hooks,
ROI, stoploss and order types so the native helper can complete enough trades.

## Mandatory gates

- 31/31 alpha/dataframe parity.
- Full-universe recursive signal stability at multiple anchors/startup lengths.
- Native Freqtrade lookahead CSV with an explicit non-biased verdict and
  sufficient completed trades.

The workflow fails closed if any mandatory gate is absent or ambiguous.

## Explicit non-claims

A PASS does **not**:

- validate the champion's complete execution callback path;
- authorize promotion, hyperopt, OOS, dry-run or live trading;
- establish tick-level fill realism, capacity or cost robustness;
- replace nested walk-forward, pair holdout/LOPO or final untouched OOS.

The champion remains `M4PioneerValidationV14` / alpha parent
`M4PioneerStableExposureV10`.  The diagnostic class must never be traded.
