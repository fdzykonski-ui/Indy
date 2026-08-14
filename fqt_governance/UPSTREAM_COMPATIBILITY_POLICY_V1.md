# FQT Freqtrade Upstream Compatibility Policy V1

## Frozen validation runtime

The active V14/V10 evidence chain is bound to Freqtrade commit
`77cabd291fa656ec6a1d237cfa524ee792133d89`.  No upstream package or source
upgrade is mixed into IP07, IP08, the deterministic baseline or a final OOS.

## Monitoring

A read-only upstream snapshot may record:

- latest official release tag and publication date;
- current official `develop` commit;
- changes to backtesting, lookahead, recursive, strategy callback, exchange or
  result-export semantics;
- security or correctness fixes relevant to the frozen environment.

Monitoring evidence cannot change the validated runtime.

## Compatibility branch

An upgrade requires a separate branch and work package with:

1. exact old/new source commits and dependency locks;
2. strategy/config/data hashes;
3. data and strategy resolver parity;
4. semantic trade-ledger comparison on the frozen baseline;
5. lookahead and recursive gates under both versions;
6. callback and execution-regression analysis;
7. fee/slippage/delay stress comparison;
8. explicit adoption or rejection receipt.

Any unexplained trade, signal, fill, fee, drawdown or result-schema difference
is a compatibility blocker.

## Adoption rule

Adopt the new runtime only when the change is either semantically equivalent or
a predeclared correction whose effect is fully revalidated through the gate
DAG.  A newer version number alone is not a reason to invalidate or silently
rewrite the current evidence chain.
