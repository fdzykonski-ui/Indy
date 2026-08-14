# FQT Strategy R&D Operating Model V2.3

## 1. Mission and safety boundary

FQT develops reproducible, causally valid and execution-aware Freqtrade
strategies.  Profit is never accepted as a substitute for correctness.
Historical results do not authorize dry-run or live trading.  Live trading is
forbidden until all predecessor gates, an untouched OOS decision, a persistent
dry-run and an independent review have passed.

## 2. Logical roles

The roles are independent review lenses coordinated by one project governor;
they are not separate autonomous persons.

| Role | Primary accountability | Mandatory output |
|---|---|---|
| Project Governor | scope, WIP, gate order, decisions | decision receipt, gate matrix |
| Research Lead | hypotheses, alternatives, falsification | research dossier, negative-results ledger |
| Strategy Engineer | minimal causal implementation | strategy diff, mechanism contract |
| Data Engineer | provenance, PIT universe, integrity | data manifest, integrity receipt |
| Validation Lead | lookahead, recursive, WF, OOS | validation receipts and raw logs |
| Execution Lead | fees, spread, slippage, latency, capacity | execution-stress matrix |
| Statistics Lead | uncertainty, multiplicity, power | statistical receipt |
| QA / Red Team | leakage, false passes, reproducibility | defect/CAPA and independent audit |
| Release Manager | freeze, hashes, package, rollback | release manifest and clean-extract test |

## 3. WIP and branch policy

- One champion and at most one alpha challenger.
- Diagnostic strategies use a dedicated branch and can never be promoted.
- No hyperopt while a correctness predecessor is open.
- No pair removal based only on the same interval used to discover the weakness.
- Every branch states one hypothesis, one primary metric and one kill criterion.
- Failed experiments remain in the negative-results ledger.

## 4. Evidence status machine

Only these states are allowed:

- `VERIFIED`: native artifact, command, inputs, hashes and acceptance criterion exist.
- `PARTIAL`: useful evidence exists but coverage or mechanism is incomplete.
- `NOT_RUN`: no executable evidence.
- `BLOCKED`: a predecessor, capability or safety gate prevents execution.
- `INVALID`: a tool ran but did not produce a valid verdict.
- `CONTAMINATED`: the interval is known/reused and cannot serve as pristine OOS.

No `PASS` is inferred from an empty CSV, a zero-trade run, a parser fallback or
an assistant claim without an artifact.

## 5. Gate DAG

1. `G00_CONTRACT` — market, pairs, timeframe, intervals, fees, wallet, stake and KPI freeze.
2. `G01_PROVENANCE_DATA` — source commit, package lock, checksums, gaps, duplicates, PIT and capacity warnings.
3. `G02_STATIC_CAUSALITY` — syntax, resolver, banned operations, future-append metamorphic checks.
4. `G03_SIGNAL_LOOKAHEAD_NATIVE` — sufficient native helper trades and explicit verdict.
5. `G04_CHAMPION_EXECUTION_CAUSALITY` — champion callbacks, state, slots and capital path.
6. `G05_RECURSIVE_INDICATORS` — official/full-universe convergence and startup justification.
7. `G06_DETERMINISTIC_BASELINE` — two semantic trade ledgers and golden hashes.
8. `G07_FUNNEL_INSTRUMENTATION` — raw signals → gates → rejects → fills → exits.
9. `G08_EXECUTION_REALISM` — fee, spread, slippage, latency, timeout, capacity and partial-fill stress.
10. `G09_NESTED_WALK_FORWARD` — purged/embargoed outer folds; inner tuning only.
11. `G10_PAIR_HOLDOUT_LOPO` — pair holdout, leave-one-pair-out and top-N concentration removal.
12. `G11_STATISTICS` — block bootstrap, dependence-aware uncertainty, multiplicity and power.
13. `G12_FINAL_UNTOUCHED_OOS` — one-shot sealed interval after all predecessors pass.
14. `G13_PERSISTENT_DRY_RUN` — uptime, reconciliation, order audit and drift monitoring.
15. `G14_INDEPENDENT_REVIEW` — red-team reproducibility and release audit.
16. `G15_CANARY_LIVE` — requires a new explicit authorization; otherwise forbidden.

A failed or invalid predecessor blocks every successor.

## 6. Standard iteration

`Critique → mechanism hypothesis → minimal repair → unit/static test → native gate → regression → new requirements → audit → CAPA → decision → next iteration`

Each iteration produces:

1. `PROJECT_FREEZE.json`
2. `TEST_CONTRACT.json`
3. raw command log and exit code
4. native result artifact
5. parser-independent summary
6. defect/CAPA receipt for every failure
7. comparison and uncertainty table
8. `DECISION_RECEIPT.json`
9. next-iteration copy/paste command

## 7. Promotion rule

A challenger promotes only when it:

- changes one causal mechanism;
- preserves all correctness gates;
- improves a predeclared outer-fold primary metric with acceptable uncertainty;
- survives pair holdout/LOPO and adverse execution stress;
- passes the single untouched OOS;
- has no material risk regression;
- receives independent review.

Otherwise: `KEEP_CHAMPION`, `REJECT`, `QUARANTINE` or `NO_CHANGE_JUSTIFIED`.

## 8. Current priority

1. Close the execution-neutral signal-generation lookahead harness (`IP07`).
2. Close the frozen champion execution-callback causality gate.
3. Close official full-universe recursive indicator convergence.
4. Instrument the complete signal/rejection/fill funnel.
5. Repair execution-cost and +1-candle timing fragility.
6. Only then permit one minimal challenger.
7. Run nested WF and pair holdout/LOPO.
8. Keep future OOS sealed and dry-run stopped until authorization.
