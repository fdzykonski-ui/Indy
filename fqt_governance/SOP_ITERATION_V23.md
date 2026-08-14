# FQT Iteration SOP V2.3

## Trigger

An iteration starts from one of:

- a failed/invalid gate;
- a falsifiable research hypothesis;
- an independently reproduced regression;
- a planned compatibility or execution-realism check.

Profit dissatisfaction alone is not a valid trigger for unconstrained tuning.

## Process chain

### 1. Critique

1. Load the previous decision receipt and next-iteration prompt.
2. Verify champion, alpha parent, hashes, data root and gate status.
3. State observed versus expected behavior.
4. Separate correctness, execution, risk, statistics and release concerns.
5. Rank the single bottleneck by safety and decision impact.

**Output:** critique note and active work-package ID.

### 2. Hypothesis and alternatives

1. State one directed mechanism hypothesis.
2. State at least two alternative explanations.
3. Predeclare primary metric, secondary risks and kill criterion.
4. Identify the data interval and contamination class.
5. Record the multiple-testing family and prior trial count.

**Output:** experiment contract.

### 3. Minimal improvement or repair

1. Modify the smallest causal surface.
2. Keep alpha unchanged for diagnostic/infrastructure repairs.
3. Keep champion and challenger physically separate.
4. Add instrumentation before relaxing filters or increasing frequency.
5. Record rollback hashes.

**Output:** diff, mechanism contract and rollback point.

### 4. Test

Execute in order:

1. syntax/schema/safety;
2. unit/static/metamorphic;
3. native correctness tool;
4. deterministic semantic regression;
5. execution stress;
6. chronological outer validation;
7. pair robustness;
8. statistics;
9. untouched OOS only after authorization.

A missing artifact, empty verdict or timeout is not a pass.

**Output:** raw logs, result archives and universal receipt.

### 5. New requirements

Every failure creates one of:

- a new hard predecessor gate;
- a CAPA action;
- an instrumentation requirement;
- a data/capability requirement;
- a rejected hypothesis in the negative-results ledger.

Requirements cannot retroactively weaken the original KPI or acceptance rule.

### 6. Audit and red team

1. Recompute hashes and summary metrics independently.
2. Challenge leakage, selection bias, pair concentration and execution realism.
3. Verify exact command, exit code and environment.
4. Check secret/live safety and clean extraction.
5. Reproduce the most load-bearing result from raw evidence.

**Output:** independent audit and any reopened defect.

### 7. CAPA

For every S1/S2 defect:

1. minimal reproducer;
2. fault tree;
3. root-cause confidence;
4. corrective action;
5. preventive control;
6. target verification;
7. regression test;
8. rollback.

A workaround may collect evidence but cannot close a broader gate than it tests.

### 8. Decision

Allowed outcomes:

- `KEEP_CHAMPION`
- `PROMOTE`
- `REJECT`
- `QUARANTINE`
- `NO_CHANGE_JUSTIFIED`
- `BLOCKED`
- `INCONCLUSIVE`

The decision receipt cites exact evidence and uncertainty. `PROMOTE` requires all
predecessor gates; otherwise it is schema-invalid.

### 9. Release/package

1. freeze strategy/config/data/runtime hashes;
2. include raw and compact evidence maps;
3. run secret scan, CRC and clean-extract validation;
4. publish compact durable status;
5. retain raw archives according to the compute plan;
6. keep credentials blank and live disabled.

### 10. Next iteration

Create one copy/paste command containing:

- mode and champion;
- WIP limit;
- active predecessor/work package;
- tasks and acceptance;
- kill criterion;
- on-pass successor;
- OOS/dry-run/live safety state.

Then begin only the first authorized work package.
