# FQT Challenger Selection Contract V1

## Preconditions

No alpha challenger may be created until:

1. IP07 signal-generation correctness has an explicit valid verdict.
2. IP08 champion execution-callback causality is closed.
3. Full-universe recursive indicator convergence is closed.
4. Signal → gate → rejection → fill instrumentation reconciles end to end.
5. Required execution-cost scenarios are defined and reproducible.

Until then, the mandatory development decision is `NO_CHANGE_JUSTIFIED`.

## Selection rule

The funnel and outer-fold evidence select exactly one mechanism family:

| Observed mechanism | Permitted challenger | Required evidence before implementation |
|---|---|---|
| Edge disappears primarily through spread/slippage or stale fills | Execution-margin filter | adverse spread/slippage attribution by pair/session and no same-period pair cherry-pick |
| Loss tail is concentrated in identifiable pre-entry risk states | Loss-tail brake | repeated outer-fold conditional tail loss and acceptable missed-winner cost |
| One path is repeatedly negative after multiplicity control | Remove or quarantine that path | negative contribution in multiple outer folds and pair holdouts |
| Entry collision/slot rejection is the bottleneck | Collision/priority policy | reconciled opportunity-cost matrix and fixed capital contract |
| Exit latency creates losses after signal invalidation | Minimal exit-timing repair | causal timestamp-prefix evidence and adverse-delay validation |

The current known-development observation that `fp_vwap_reclaim` is negative is
not sufficient by itself to remove it; the same period helped discover the
weakness.  It becomes actionable only after outer-fold confirmation.

## Experiment contract

Every challenger must predeclare:

- one mechanism and one code diff surface;
- one primary metric and its direction;
- secondary risk and activity metrics;
- minimum effective sample size;
- outer folds, purging and embargo;
- pair holdout/LOPO protocol;
- cost/slippage/delay scenarios;
- multiplicity family and trial count;
- kill criterion and rollback hash.

## Promotion criterion

Promotion requires paired outer-fold improvement with acceptable uncertainty,
no correctness regression, no material concentration regression, positive
required execution-stress performance, a one-shot untouched OOS pass and an
independent audit.  Development-period KPI improvement alone cannot promote.
