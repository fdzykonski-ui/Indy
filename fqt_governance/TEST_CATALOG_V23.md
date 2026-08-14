# FQT Strategy Validation Test Catalog V2.3

## Correctness and causality

| Test ID | Test | Primary failure condition | Required artifact | Current state |
|---|---|---|---|---|
| T-C01 | Python compile and strategy resolver | compile/resolver error or duplicate ambiguity | compile log, resolver table | verified |
| T-C02 | Static future-operation audit | negative shift, centered future window or unsafe global aggregation | static audit JSON | verified/continuous |
| T-C03 | Future-append metamorphic dataframe test | historical indicator/signal/tag value changes after future append | pair/cut matrix | verified limited; IP07 extends |
| T-C04 | Native lookahead signal generation | insufficient trades, empty verdict or bias | raw log, CSV, summary | active IP07 |
| T-C05 | Champion execution callback causality | future/state-dependent callback output | callback prefix/pair-order/capital matrix | active IP08 |
| T-C06 | Recursive indicator convergence | material signal-dependent drift across startup histories | official report plus full-universe matrix | partial |
| T-C07 | Same-candle entry/exit and collision | order/exit decision uses unavailable candle state | collision ledger | not run |
| T-C08 | Deterministic semantic reproduction | trade-ledger or summary differences across exact reruns | two result ZIPs and semantic diff | verified |

## Baselines and ablations

| Test ID | Test | Purpose | Kill condition |
|---|---|---|---|
| T-B01 | Always-BTC / BTC+Cash | market exposure benchmark | champion does not improve risk-adjusted outcome |
| T-B02 | EMA/SMA trend | simple trend benchmark | complex strategy has no robust uplift |
| T-B03 | Breakout | simple opportunity benchmark | complex entry logic adds no outer-fold uplift |
| T-B04 | ROI-only | isolate exit contribution | custom exits do not improve tails/net outcome |
| T-B05 | Stoploss-only | isolate loss control | custom logic increases tail loss |
| T-B06 | Random/reversed signals | leakage/sanity negative control | random/reversed performs implausibly well |
| T-B07 | No-risk-gates | risk-gate contribution | gates only reduce activity without risk benefit |
| T-B08 | Path/gate ablation | causal contribution | removed component improves repeatedly or retained component adds no value |
| T-B09 | Capital/stake ablation | separate alpha from allocation | result depends primarily on compounding/selective stake |
| T-B10 | Protections on/off | verify protection effect | configured protection is inert or harmful |

## Execution realism

| Test ID | Scenario family | Required values | Hard failure |
|---|---|---|---|
| T-E01 | Fees each side | 0.10%, 0.12%, 0.15%, 0.20%, 0.30% | required scenario profit <=0 or PF <=1 |
| T-E02 | Spread | 0, 2, 5, 10, 20 bps adverse | required scenario profit <=0 or PF <=1 |
| T-E03 | Slippage | 0, 2, 5, 10, 20 bps adverse | required scenario profit <=0 or PF <=1 |
| T-E04 | Entry delay | +0, +1, +2 completed candles | +1 required scenario fails |
| T-E05 | Exit delay | +0, +1, +2 completed candles | tail loss or MDD exceeds contract |
| T-E06 | Partial fill | 100%, 75%, 50% | capacity-adjusted result fails |
| T-E07 | Timeout/cancel | 1, 5, 10 minutes | result relies on unrealistic indefinite fills |
| T-E08 | Minimum notional/precision | historical pair constraints | invalid order rate material |
| T-E09 | Capacity | pair/session participation caps | profit disappears at deployable size |
| T-E10 | Pair-order/slot contention | permutations at fixed capital | unexplained order-dependent alpha |

## Chronological and pair validation

| Test ID | Test | Required design | Hard failure |
|---|---|---|---|
| T-V01 | Fast chronological folds | train/validate order preserved | negative or unstable validation |
| T-V02 | Rolling nested WF | outer folds; inner tuning only | no paired outer-fold uplift |
| T-V03 | Anchored nested WF | expanding train; outer test | instability/regime collapse |
| T-V04 | Purging/embargo | overlap removed around labels/trades | leakage-sensitive uplift |
| T-V05 | Pair holdout | pairs absent from model selection | held-out failure/concentration |
| T-V06 | Leave-one-pair-out | repeat across all pairs | reliance on single contributor |
| T-V07 | Top-N profit removal | N=1,3,5,10 | residual strategy nonviable |
| T-V08 | Regime/session/month slices | predeclared subgroups | hidden catastrophic subgroup |

## Statistics

| Test ID | Test | Requirement | Limitation to report |
|---|---|---|---|
| T-S01 | Trade bootstrap | dependence caveat explicit | IID assumption |
| T-S02 | Block bootstrap | block size sensitivity | finite block count |
| T-S03 | Monte Carlo/permutation | seed and iterations fixed | path assumptions |
| T-S04 | Paired outer-fold comparison | champion/challenger same folds | fold count/power |
| T-S05 | Multiplicity control | family and trial count logged | exploratory versus confirmatory status |
| T-S06 | Parameter stability | neighboring plateau and seeds | optimizer selection uncertainty |
| T-S07 | Power/sensitivity | minimum detectable uplift | low-trade/fold uncertainty |

## Final release validation

| Test ID | Gate | Acceptance |
|---|---|---|
| T-R01 | Final untouched OOS | all predecessors pass; one sealed execution; no post-open repair |
| T-R02 | Persistent dry-run | >=28 days, >=500 closed trades, >=99% uptime, reconciliation and drift monitoring |
| T-R03 | Independent reproduction | clean environment reproduces hashes/metrics within tolerance |
| T-R04 | Secret/live safety | credentials absent, state stopped, no real orders, kill switch tested |
| T-R05 | Canary | separate explicit authorization, tiny exposure and immediate rollback |

No `NOT_RUN`, `INVALID`, `BLOCKED` or `CONTAMINATED` result can be promoted by a
high composite score from another test family.
