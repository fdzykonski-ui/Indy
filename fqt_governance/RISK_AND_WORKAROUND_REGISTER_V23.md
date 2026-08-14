# FQT Risk and Workaround Register V2.3

A workaround may unblock evidence collection, but it cannot silently redefine a
gate or promote the champion.

| ID | Open risk/gate | Severity | Direct solution | Allowed workaround now | Residual limitation | Owner roles |
|---|---|---:|---|---|---|---|
| R-001 | Native champion lookahead completes one trade and emits no verdict | S2 | execution-preserving native callback harness | IP07 execution-neutral class after 31-pair alpha parity | closes signal generation only, not champion execution callbacks | Validation, Strategy, QA |
| R-002 | Champion custom stake/exit/order callbacks not causally closed | S2 | timestamp-prefix, pair-order, capital/slot and order-state matrices | static callback/state graph and callback-prefix subgate | pair-order and capital/slot semantics remain open | Strategy, Validation, Execution |
| R-003 | Full official recursive indicator gate missing | S2 | official 31-pair recursive-analysis with startup justification | custom 31-pair recursive signal matrix | indicator drift remains a separate explicit gate | Validation, Statistics |
| R-004 | Fee 0.20/0.30% and delay +1 fail | S1 performance | isolate signal decay, spread, slippage, fill and timeout mechanisms | staged adverse stress pipeline; no alpha change yet | no cost-robust edge until passed | Execution, Strategy |
| R-005 | Raw signal/gate/rejection/fill funnel absent | S2 | semantic-parity instrumentation patch | declarative counter contract and reconciliation plan | no entry-frequency repair justified yet | Strategy, Execution, QA |
| R-006 | Pair concentration and no LOPO | S2 | pair holdout, LOPO, top-N removal across outer folds | concentration/HHI diagnostics on development | development concentration cannot promote or prune pairs | Validation, Statistics, Data |
| R-007 | Known May–June evaluation is contaminated | S1 validation | seal a later untouched period and execute once after predecessors | keep all future OOS data closed | no current OOS claim | Governor, Data, Validation |
| R-008 | No persistent forward dry-run | S1 release | 28-day/500-trade monitored dry-run after OOS | none; historical replay remains backtest | no forward execution evidence | Release, Execution, QA |
| R-009 | Candle-only fills and zero-volume minutes | S2 execution | historical PIT market metadata plus spread/orderbook/capacity model | adverse spread/slippage and conservative notional caps | tick/queue/market-impact uncertainty remains | Data, Execution |
| R-010 | Upstream Freqtrade changes may alter semantics | S2 reproducibility | separate compatibility branch and full parity/regression | freeze commit `77cabd291` during IP07/IP08 | no benefit from upstream fixes inside current evidence chain | Release, Validation |
| R-011 | Heavy workflow failure may lose evidence | S2 operations | always-upload raw evidence and durable compact publisher | independent collector downloads artifact and commits compact status | artifact must still be produced before hard runner loss | Release, QA |
| R-012 | Duplicate expensive runs | S3 resources | stable concurrency groups after current run | WIP registry and collector; do not restart active IP07 | current active workflow is intentionally not rewritten mid-run | Governor, Release |
| R-013 | Strategy zoo/hyperopt before correctness | S1 governance | enforce predecessor DAG and one-challenger WIP | `NO_CHANGE_JUSTIFIED` and gate orchestrator | performance development remains paused | Governor, Research, QA |
| R-014 | Live order risk | S1 safety | final OOS, dry-run, review and new explicit authorization | blank credentials, stopped state, live flags false | no live trading capability is exercised | Governor, Release, QA |

## Priority

1. R-001 and R-002.
2. R-003 and R-005.
3. R-004 and R-009.
4. R-006, nested WF and statistics.
5. R-007 through R-008.
6. R-014 remains blocked until a separate future authorization.
