# FQT V29 Primary-Source Research Register

## Scope

The register is frozen before any V29 OOS result is inspected.  Sources are
used to define correctness, validation, execution and multiple-testing gates;
they are not used to manufacture pair/date-specific alpha.

| Source | Class | V29 application |
|---|---|---|
| Freqtrade 2026.7 release | official release | isolated compatibility install and runtime lock |
| Freqtrade lookahead-analysis documentation | official documentation | market-order correctness lane, minimum/nonempty coverage and bias verdict |
| Freqtrade recursive-analysis documentation | official documentation | startup-candle/indicator stability lane |
| Freqtrade backtesting documentation | official documentation | deterministic export, fee and timerange contracts |
| Freqtrade hyperopt documentation | official documentation | training-only multi-seed diagnostic; no OOS hyperoptimization |
| Freqtrade strategy callbacks documentation | official documentation | custom stake/exit/state and callback causality audit |
| Binance Public Data repository | official exchange source | daily/monthly 1m archives, CHECKSUM verification and no candle synthesis |
| Bailey et al., *The Probability of Backtest Overfitting* | primary paper | CSCV/PBO requirement after repeated candidate search |
| Bailey & López de Prado, *The Deflated Sharpe Ratio* | primary paper | adjust performance significance for non-normality and trial multiplicity |
| White, *A Reality Check for Data Snooping* | primary paper | family-wise benchmark challenge for candidate families |

## URLs

- https://github.com/freqtrade/freqtrade/releases/tag/2026.7
- https://www.freqtrade.io/en/stable/lookahead-analysis/
- https://www.freqtrade.io/en/stable/recursive-analysis/
- https://www.freqtrade.io/en/stable/backtesting/
- https://www.freqtrade.io/en/stable/hyperopt/
- https://www.freqtrade.io/en/stable/strategy-callbacks/
- https://github.com/binance/binance-public-data
- https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
- https://doi.org/10.1111/1468-0262.00152

## Derived controls

1. A lookahead run with no usable trade/signal coverage is invalid rather than a pass.
2. Market-order lookahead is the correctness verdict; limit-order behavior is a separate fill-stress lane.
3. Recursive stability is necessary but does not establish profitability or OOS validity.
4. Hyperopt may use only training data and each seed/epoch family enters the trial ledger.
5. Binance gaps are repaired only from another checksummed official archive; otherwise they remain disclosed gaps.
6. Candidate promotion requires cost and delay margin, not merely high raw win rate.
7. OOS is opened once and cannot be used for post-hoc pair or threshold selection.
8. PBO/DSR/Reality-Check controls are required before a repeated-search result is called statistically exceptional.
