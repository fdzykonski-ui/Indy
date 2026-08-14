# FQT Resource and Compute Plan V2.3

## Objectives

- Reserve expensive compute for gates that can change a decision.
- Avoid duplicate 31-pair executions.
- Preserve raw evidence long enough for review while publishing compact durable
  summaries to the branch.
- Keep alpha WIP at one and diagnostic WIP at one.

## Workload classes

| Class | Typical workload | Runtime envelope | Memory envelope | Execution venue | Retention |
|---|---|---:|---:|---|---:|
| C0 | JSON/YAML/schema, Python compile, shell syntax, secrets | <15 min | <2 GB | GitHub hosted CI | 14 days |
| C1 | Static strategy/callback audit, compact parsers | <30 min | <4 GB | GitHub hosted CI/local | 14 days |
| C2 | 7-pair smoke/metamorphic test | <60 min | <8 GB | local or hosted CI | 7 days |
| C3 | 31-pair deterministic backtest, parity, recursive or lookahead | 1–6 h | 8–16 GB | hosted Ubuntu 24.04 or dedicated local runner | raw 3–7 days; compact durable |
| C4 | Nested WF, LOPO, execution matrix | 6–48 h per controlled batch | 16–32 GB | dedicated local runner preferred | raw 14 days; compact durable |
| C5 | Hyperopt after authorization | bounded epoch/seed budget | 16–32 GB | dedicated local runner | winners + trial ledger |

Runtime envelopes are scheduling bounds, not evidence. Actual timestamps and
resource metrics belong in each run receipt.

## Current allocation

### IP07

- One C3 full-universe correctness run.
- One independent local full-run fallback is permitted because it uses an
  already reconstructed frozen runtime and creates a separate receipt.
- Do not launch another heavy run while either evidence source is active.
- A resilient collector publishes compact status even when the heavy workflow
  concludes with failure.

### IP08

- Static inventory: C0/C1 and automatic.
- Callback-prefix harness: C3, manual only after IP07 evaluation.
- Pair-order, capital/slot and same-candle matrices are separate batches so a
  failed subgate does not force rerunning unrelated evidence.

## Future budgets

### Funnel instrumentation

One deterministic baseline plus one instrumented semantic-parity run. The
instrumented run must reproduce the trade ledger before any funnel statistics
are accepted.

### Execution matrix

Use staged elimination:

1. fee and +1-candle delay gates;
2. spread/slippage grid only if stage 1 is viable;
3. partial-fill/timeout/capacity only for surviving candidates.

Stop the batch immediately after a hard kill criterion.

### Challenger and nested WF

- One challenger mechanism.
- Fast screening: two outer folds, no hyperopt.
- Full nested WF only after screening survives.
- Hyperopt budget is declared in advance by epochs × seeds × folds.
- No post-hoc extension of the budget because results are disappointing.

## Artifact policy

- Raw large result archives: immutable, hash-indexed and short/medium retention.
- Compact JSON/CSV summaries, commands, logs extracts and hashes: committed to
  the evidence branch.
- Empty CSV, missing result, timeout or artifact upload failure is `INVALID` or
  `BLOCKED`, never a pass.
- Credentials, databases and exchange secrets are never packaged.

## Concurrency policy

Before modifying a heavy workflow, confirm that no current run is active. Future
heavy workflows must use a stable concurrency group and cancel superseded runs,
but the active IP07 workflow is not rewritten mid-run because that would create
a new execution and destroy current progress.
