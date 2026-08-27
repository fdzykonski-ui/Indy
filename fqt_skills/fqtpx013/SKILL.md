# fqtpx013 — Execution Microstructure & Cost Margin

Status: project-local FQT skill contract.

## Purpose
Distinguish candle-model profit from executable net edge.

## Mandatory controls
- Test fees 0.10–0.30% per side, adverse spread and slippage.
- Test entry delay +1/+2, pair ordering, slot count, wallet and stake.
- Attribute PnL to ROI, profit lock, emergency exit, stoploss and force exit.
- Reject any candidate with negative mandatory base stress or PF <= 1.
- Do not treat a limit-order lookahead false positive as a market-order verdict.

## Deliverables
Execution-margin matrix, MAE/MFE ledger, tail-loss attribution and kill criteria.
