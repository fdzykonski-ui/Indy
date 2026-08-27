# fqtpx012 — Exchange Data Gap Reconciliation

Status: project-local FQT skill contract.

## Purpose
Validate Binance archive integrity without silently fabricating missing candles.

## Mandatory controls
- Verify ZIP CRC and companion SHA-256 CHECKSUM.
- Cross-check incomplete monthly archives against official daily archives.
- Repair monthly omissions only with identical official daily candles.
- Retain exchange-native gaps explicitly; never synthesize OHLCV.
- Separate research eligibility from execution/OOS eligibility.

## Deliverables
Data manifest, gap ranges, repair receipts, execution-ineligible pair list and dataset root hash.
