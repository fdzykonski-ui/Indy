# fqtpx018 — OOS Vault, Dry-Run Canary & Drift

Status: project-local FQT skill contract.

## Purpose
Protect the one-shot holdout and govern forward validation.

## Mandatory controls
- Freeze OOS data before inspection and open it once only.
- Forbid threshold revision or pair reselection after OOS opening.
- Require a keyless, stopped dry-run preflight before any persistent process.
- Define minimum duration, trade count, uptime and kill switches.
- Monitor signal, data, rejection, fee, slippage, drawdown and regime drift.

## Deliverables
OOS authorization, one-shot execution receipt, 28-day canary contract and drift dashboard schema.
