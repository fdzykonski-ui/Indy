# FQT IP08 — Champion execution-callback causality

## Scope

IP07 isolates dataframe-level signal generation. IP08 addresses the remaining
champion execution path: capital and slot state, custom stake, custom exits,
entry/exit price callbacks, order confirmations and any state shared across
pairs or timestamps.

The initial static inventory identifies effective callbacks and constructs a
state-dependency graph. Static evidence is not a causal PASS.

## Planned executable test sequence

1. **Callback inventory and disabled-path assertions.** Verify exactly which
   callback implementation is effective through the V14/V10 class lineage.
2. **Timestamp-prefix replay.** At each selected trade timestamp, invoke the
   callback with data ending exactly at that timestamp and compare it with the
   same prefix extracted after future candles are appended.
3. **Pair-order permutation.** Replay the same timestamp under multiple pair
   processing orders while wallet and slot state are fixed.
4. **Capital/slot ablation.** Separate signal generation from wallet balance,
   proposed stake, max-open-trades and rejected-entry effects.
5. **Same-candle and order-state matrix.** Cover entry/exit collisions,
   unfilled orders, force exits, timeout and confirmation hooks.
6. **Execution-preserving native harness.** Run a native helper adapter only
   after semantic signal parity and explicit callback boundaries are proven.

## Acceptance

- No future-candle dependency in any active callback.
- Every mutable state dependency is causal, timestamp-scoped and test-covered.
- Pair-order changes do not alter decisions unless the difference is explicitly
  caused by the frozen slot/capital contract and is recorded as portfolio
  semantics rather than alpha.
- Native and custom receipts expose commands, exit codes, hashes and raw logs.

## Safety

IP08 cannot authorize promotion, OOS, dry-run or live trading. The champion
remains unchanged until this gate and all downstream validation gates pass.
