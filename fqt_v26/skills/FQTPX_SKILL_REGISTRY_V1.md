# FQT Pioneer Skill Pack — fqtpx001…fqtpx009

Status: project-local, versioned, fail-closed. These identifiers are not third-party plugin packages; they are executable FQT process skills bound to this repository and pipeline.

## fqtpx001 — Contract & Governance Freeze
Inputs: strategy, config, runtime, pair universe, data ranges. Outputs: hashes, WIP limit, champion/challenger state, authorization matrix. Kill: any mutable or missing contract field.

## fqtpx002 — Data Integrity, PIT & Survivorship
Inputs: official Binance archives/checksums and exchange metadata. Outputs: gap/duplicate/OHLCV/volume/listing/filter/capacity matrix. Kill: first checksum, schema, timestamp or eligibility defect.

## fqtpx003 — Causality & Correctness
Inputs: strategy callbacks and data. Outputs: static audit, corrected native lookahead, future-append metamorphic tests, recursive analysis, same-candle/callback audit. Kill: bias, material recursive drift, ambiguous verdict or insufficient coverage.

## fqtpx004 — Deterministic Backtesting & Controls
Inputs: frozen runtime/data/strategy/config. Outputs: two-run semantic-ledger hash, naive baselines, reverse/delay controls, month/session/regime splits. Kill: any semantic ledger divergence.

## fqtpx005 — Training-Only Optimization & Walk-Forward
Inputs: development folds only. Outputs: preregistered candidates, multi-seed hyperopt, parameter neighborhood/plateau, purged/embargoed rolling and anchored WF. Kill: no plateau, unstable seeds, outer-fold regression.

## fqtpx006 — Ablation, Pair Holdout & Concentration
Inputs: candidate and frozen pair universe. Outputs: entry/exit/gate/indicator ablations, LOPO, pair-order reversal, top-N removal, concentration metrics. Kill: dependence on one pair/path or post-hoc pair deletion.

## fqtpx007 — Execution & Risk Stress
Inputs: selected candidate. Outputs: fee 0.10–0.30%, spread/slippage, delay +1/+2, protections, wallet/stake/slot stress, fault injection and tail-risk matrix. Kill: non-positive net edge, PF≤1, DD breach or operational fault.

## fqtpx008 — Statistics & One-Shot OOS
Inputs: fully gated candidate and sealed OOS. Outputs: bootstrap, Monte Carlo, multiple-testing correction, one-shot candidate-vs-anchor OOS comparison and immutable receipt. Kill: any predecessor gate not PASS; no threshold revision after opening.

## fqtpx009 — Forward Canary & Release
Inputs: OOS-PASS candidate. Outputs: keyless dry-run preflight, 28-day canary contract, reconciliation, drift/risk monitors, independent release decision. Kill: no live capital; live requires separate explicit authorization.

## Pipeline order
`fqtpx001 → fqtpx002 → fqtpx003 → fqtpx004 → fqtpx005 → fqtpx006 → fqtpx007 → fqtpx008 → fqtpx009`

Global rules: timestamp/date/winner replay forbidden; fresh OOS remains sealed until fqtpx001–007 PASS; dry-run is not historical replay; status vocabulary is PASS/FAIL/BLOCKED/NOT_RUN/CONTAMINATED; targets are never weakened after results are known.
