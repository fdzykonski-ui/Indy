# FQT Project Status — 2026-08-14

## Decision

`KEEP_CHAMPION`

- Champion: `M4PioneerValidationV14`
- Alpha parent: `M4PioneerStableExposureV10`
- Alpha change in this iteration: `false`
- Promotion: blocked
- Final untouched OOS: not opened
- Persistent dry-run: not started
- Live trading: forbidden

## Frozen deterministic baseline

| Metric | Value |
|---|---:|
| Development interval | 2026-01-01 to 2026-05-01, half-open |
| Pairs / timeframe | 31 / 1m |
| Trades | 663 |
| Wins / draws / losses | 555 / 0 / 108 |
| Win rate | 83.7104% |
| Net profit | +195.125898 USDC / +19.512590% |
| Profit factor | 4.237836 |
| Wallet drawdown | 2.89% |
| Semantic trade-ledger SHA-256 | `d0e939e9ed87b864782d3f10cd3afc84328092efb8b80e69011c5fe513e03d65` |

The activity, win-rate and drawdown targets pass; the >80% profit and >5 profit
factor targets fail.

## Critical known failures

- Native champion lookahead helper: one completed trade, zero valid verdict rows.
- Fee 0.20% per side: approximately break-even/negative, PF approximately 1.
- Fee 0.30% per side: negative, PF below 1.
- Entry delay +1 completed candle: negative, PF below 1.
- Known May–June evaluation: contaminated; PF 1.83 and wallet MDD 7.63%.
- Full official recursive indicator gate, nested WF and pair holdout/LOPO remain open.

## Active implementation

### IP07 — signal-generation correctness

Implemented on branch `fqt-rnd-v23-next-20260814`:

- execution-neutral diagnostic class;
- full 31-pair alpha/dataframe parity;
- full-universe recursive signal matrix;
- native lookahead analysis;
- fail-closed summarizer;
- compact evidence publisher and resilient artifact collector.

A PASS is scoped to signal generation and never closes the champion execution
callback gate.

### IP08 — champion execution callbacks

Started:

- static callback inventory and state-dependency graph;
- callback-prefix executable harness;
- pair-order, capital/slot and same-candle/order-state subgates specified;
- static and manual execution workflows integrated.

## Next gate order

1. Finish/evaluate IP07.
2. Close champion execution callback causality.
3. Close full official recursive indicator convergence.
4. Instrument the complete signal/rejection/fill funnel.
5. Repair execution-cost and +1-candle timing fragility.
6. Permit at most one causal challenger.
7. Nested WF, pair holdout/LOPO and statistics.
8. One-shot untouched OOS.
9. Persistent dry-run, independent review and only then a separately authorized canary.
