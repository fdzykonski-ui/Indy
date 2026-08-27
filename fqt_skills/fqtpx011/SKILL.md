# fqtpx011 — Bias & Leakage Forensics

Status: project-local FQT skill contract.

## Purpose
Close lookahead, callback-state, same-candle and signal-reapplication defects before any alpha work.

## Mandatory controls
- Run native market-order `lookahead-analysis`; limit-order runs are stress-only.
- Require nonempty verdicts and active entry/exit-tag coverage.
- Separate vectorized signal causality from callback/portfolio-state causality.
- Scan negative shifts, centered windows, backfills, global aggregates and timestamp replay.
- Block challenger, OOS, dry-run and live on any unresolved correctness defect.

## Deliverables
`LOOKAHEAD_RECEIPT.json`, callback event ledger, signal-hash parity matrix, RCA/CAPA.
