# fqtpx017 — Multiple-Testing, PBO & Deflated Performance

Status: project-local FQT skill contract.

## Purpose
Quantify selection bias after repeated strategies, pairs, tags, seeds and parameter trials.

## Mandatory controls
- Keep a complete trial and negative-results ledger.
- Apply CSCV/PBO when enough comparable configurations exist.
- Calculate Deflated Sharpe or an equivalent multiple-testing correction.
- Use bootstrap/Monte Carlo with dependence-aware blocks.
- Do not promote p-values, Sharpe or PF without trial-count context.

## Deliverables
Trial-family registry, PBO/DSR report, corrected confidence intervals and selection-bias warning.
