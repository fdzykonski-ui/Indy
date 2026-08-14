# FQT Work-Package Registry V2.3

## Scheduling rules

- Priority order is safety/correctness → execution realism → validation → performance.
- One active alpha work package; diagnostics may run separately but cannot promote.
- A blocked successor is not started merely to consume compute.
- Every package has a kill criterion and required evidence.

## Active

### WP-001 — IP07 signal-generation correctness harness

- **Priority:** P0
- **Owner roles:** Validation Lead, Strategy Engineer, QA/Red Team
- **Hypothesis:** the frozen V10/V14 dataframe alpha is future-causal; the prior
  invalid result is caused by helper/portfolio execution incompatibility rather
  than future data in signal generation.
- **Implementation:** execution-neutral diagnostic subclass; 31-pair parity;
  full-universe recursive signal matrix; native lookahead-analysis.
- **Acceptance:** 31/31 parity, 31/31 recursive signal stability, sufficient
  helper trades, explicit `has_bias=false`.
- **Kill:** any alpha/dataframe difference or any biased signal.
- **Non-claim:** does not close champion execution callback causality.
- **Branch:** `fqt-rnd-v23-next-20260814`

## Queued after WP-001 PASS

### WP-002 — Champion execution callback causality

- **Priority:** P0
- **Problem:** the champion's capital-, slot-, tag- and custom-exit behavior is
  not exercised validly by the generic helper.
- **Tasks:** callback inventory; state-dependency graph; custom stake/exit/order
  ablations; same-candle audit; execution-preserving diagnostic adapter;
  semantic signal and trade-ledger regression.
- **Acceptance:** explicit native verdict for the complete relevant execution
  path or a formally scoped set of callback-specific causal tests.
- **Kill:** unexplained semantic signal mutation or future state dependency.

### WP-003 — Official full-universe recursive indicator convergence

- **Priority:** P0
- **Tasks:** run official tool across 31 pairs and startup lengths; identify
  large-drift columns; map drift to signal dependencies; justify final
  `startup_candle_count` with margin.
- **Acceptance:** no material signal-dependent recursive drift; startup choice
  stable across pairs and anchors.

### WP-004 — Signal/rejection/fill funnel instrumentation

- **Priority:** P1
- **Tasks:** raw signals, each gate, pair policy, capital, slot, order creation,
  fill, timeout and exit counters; collision and kill-ratio matrices.
- **Acceptance:** every rejected opportunity has one primary attribution and
  counters reconcile end to end.
- **Kill:** non-reconciling counts or instrumentation changing trade semantics.

### WP-005 — Execution realism repair

- **Priority:** P1
- **Current failures:** fee 0.20% per side, fee 0.30% per side and entry delay +1.
- **Tasks:** separate signal decay from fill mechanics; adverse spread/slippage;
  partial fills; timeout/cancel; minimum notional; capacity by pair and session.
- **Acceptance:** positive net profit and PF >1 under the required adverse
  scenario without MDD >5%.
- **Kill:** improvement exists only under optimistic fill assumptions.

## Queued after correctness and execution realism

### WP-006 — One minimal challenger

- **Priority:** P2
- **Constraint:** exactly one causal mechanism; no pair cherry-pick; no target
  relaxation.
- **Candidate mechanisms:** loss-tail brake, execution-margin filter or removal
  of the negative VWAP-reclaim path.  The funnel evidence selects only one.
- **Acceptance:** predeclared outer-fold uplift with no correctness/risk
  regression.

### WP-007 — Nested walk-forward

- Chronological outer folds, purging and embargo.
- Inner-fold tuning only.
- Paired champion comparison, parameter stability and negative-fold retention.

### WP-008 — Pair holdout / LOPO / concentration

- Pair holdout and leave-one-pair-out.
- Top-1/3/5/10 profit-contributor removal.
- Pair concentration HHI and minimum residual profit gate.

### WP-009 — Statistical decision package

- Dependence-aware block bootstrap.
- Paired outer-fold uncertainty.
- Multiple-testing and trial ledgers.
- Power/sensitivity for the primary metric.

## Safety-blocked

### WP-010 — Final untouched OOS

Blocked until WP-001 through WP-009 and independent predecessor gates pass.
Known May–June history remains `CONTAMINATED` and cannot be relabeled.

### WP-011 — Persistent dry-run

Blocked until final untouched OOS passes.  Historical replay is not dry-run.

### WP-012 — Canary/live

Forbidden without a new explicit authorization after dry-run and independent
review.
