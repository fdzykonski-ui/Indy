# FQT V29 Pioneer Performance Factory

- Decision: **BLOCK_OOS_KEEP_CHAMPION**
- Selected candidate: **none**
- OOS opened: **False**
- Persistent dry-run: **not started**
- Live capital: **forbidden**

## 5×8 comparison

| Version/Test | Zeitraum | Start→Ende | Trades | W/L/D | WR | Profit | PF/DD |
|---|---|---|---|---|---|---|---|
| V28/V14 Baseline | 20260101–20260401 | N/V | N/V | N/V | N/V | N/V | N/V |
| V29 BLOCKED Train | 20260101–20260401 | N/V | N/V | N/V | N/V | N/V | N/V |
| V29 BLOCKED Validation | 20260401–20260623 | N/V | N/V | N/V | N/V | N/V | N/V |
| V29 Fee 0.20% | 20260401–20260623 | N/V | N/V | N/V | N/V | N/V | N/V |
| V29 OOS/Full | 20260623–20260815 | N/V | N/V | N/V | N/V | N/V | N/V |

## Repairs
1. Mixed epoch-unit handling repaired with per-value normalization.
2. Monthly Binance omissions cross-checked against checksummed daily archives.
3. Exchange-native gaps disclosed and made execution-ineligible instead of synthesized.
4. V29 candidate construction isolated from the sealed OOS interval.
5. Plus-two-candle controls added without pair/date exceptions.
6. Result collection made fail-closed even when the main driver stops early.

## Improvements
1. Five pair-agnostic causal challengers evaluated beside the frozen champion.
2. Aggressive MOT=1 spot exposure paired with shallower hard-tail controls.
3. Fee 0.30% and delay +2 added to the existing stress lattice.
4. Data integrity now requires manifest-level completeness and execution eligibility.
5. FQTPX 001–009, 011–019 and 021–029 mapped into a hashed governance ledger.
6. Final strategy/config are forced keyless, stopped and non-live.

## New developments
1. M4PioneerV29ProfitVelocity
2. M4PioneerV29TailShield
3. M4PioneerV29RegimeScore
4. M4PioneerV29AdaptiveBalanced
5. M4PioneerV29HighMargin
6. Universal causal Delay2 control family
