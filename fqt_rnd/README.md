# Freqtrade Spot/USDC 1m Research Harness

This repository is the secret-free, reproducible research layer built around
the supplied Freqtrade archive. It is deliberately separate from the immutable,
dirty upstream reconstruction at `reconstruction/freqtrade`.

The current decision is **retain historical Champion V741; no promotion, no
OOS opening, and no Canary**. The authoritative reader artifact is
`report/report.html`; machine-readable decisions and evidence remain canonical.

## Frozen scope

- Binance Spot, quote currency USDC, long-only, fixed 1-minute candles.
- No futures, shorting, grid logic, or position adjustment/uncontrolled DCA.
- `dry_run_wallet=1000`, `stake_amount=unlimited`, `max_open_trades=1` for the
  common comparison contract.
- Development window: `20260101-20260501`; training window:
  `20260101-20260301`.
- Frozen OOS: `20260502-20260509`, end-exclusive. It is intentionally sealed.
- Promotion targets are falsifiable gates, never promises: more than 500
  trades, 10–20 trades/day, winrate above 80%, net profit above 50%, finite
  Profit Factor above 5, and wallet drawdown below 5%.

The exact contract is `contracts/research_contract_v1.json`.

## Source of Truth hierarchy

1. `champion/frozen/ED8_V741_E001FastCapture10m08bp.py` and
   `champion/CHAMPION_MANIFEST.json` freeze the historical Champion by SHA-256.
2. `configs/` freezes secret-free engine settings and the one available pair.
3. `audit/source_of_truth_inventory.json` records the supplied archive,
   checkout, strategy counts, data files and evidence gaps.
4. `results/summaries/metrics_all.{json,csv}` normalizes immutable Freqtrade
   result archives; `logs/` contains the complete captured command output.
5. `decisions/promotion_decision.json` is the executable promotion decision;
   `audit/gate_matrix.json` is the full status ledger.
6. `report/artifact.json` and `report/report.html` are generated reader views,
   not replacement sources.

Every finding uses one of four labels defined in `audit/STATUS_LEGEND.md`:
`VERIFIZIERT`, `TEILWEISE VERIFIZIERT`, `NICHT VERIFIZIERT`, or `BLOCKIERT`.

## Current verified boundary

- The historical 20-trade Champion result is exactly reproduced after fixing
  the offline BTC amount precision to `1e-6`; the failed precision attempt is
  retained as evidence.
- The common 1,000-USDC development run has 20 trades, 100% winrate,
  +26.2418% net profit and 1.9145% wallet drawdown. Profit Factor is undefined
  because there are no losing trades; Freqtrade's emitted `0.0` is not treated
  as infinity or as passing the `>5` gate.
- Both registered challengers fail on training and never enter validation.
- Structural BTC/USDC data integrity, deterministic reproduction, offline
  execution timing and selected baseline/stress comparisons pass.
- Recursive stability fails at the configured startup value; lookahead has
  insufficient signal coverage. Thirty-pair survivorship and pair holdouts are
  blocked because only BTC/USDC 1m data exists.

See `report/report.html` for the complete matrix, charts, limitations and next
work packages.

## Project layout

```text
champion/       immutable Champion, manifest and controlled ablations
configs/        secret-free research and dry-run-only configurations
contracts/      frozen split, scope, metrics and promotion rules
hypotheses/     preregistered candidates and falsification criteria
strategies/     baselines, negative controls and challengers
tools/          audit, normalization, statistics and artifact builders
scripts/        complete development and Freqtrade engine pipelines
tests/          hard-constraint, catalog and immutability checks
audit/          Source-of-Truth, data, causality, security and gate evidence
results/        normalized summaries; raw result archives remain local/ignored
logs/           full captured Freqtrade and audit output
notebooks/      generated dependency-light Colab/Jupyter audit notebook
report/         canonical artifact JSON, SQLite query source and portable HTML
release/        deterministic secret-free handoff bundle
```

`reconstruction/` and `evidence/` are local immutable inputs and are excluded
from Git/release. Historical result ZIPs contain populated credential fields;
their values are never printed or republished.

## Reproduce the checked development state

Prerequisite: the supplied reconstruction must exist at
`reconstruction/freqtrade` with its `.venv` and BTC/USDC 1m data.

```bash
make verify
make development-pipeline
```

The development pipeline rebuilds data quality, normalized result summaries,
static/runtime audits, seeded statistical diagnostics, gate matrix, notebook,
verification record and the portable HTML report. Override `REPORT_BUILDER`
when the Data Analytics portable builder is installed elsewhere.

To rerun the expensive Freqtrade engine suite without touching OOS:

```bash
RUN_LABEL=manual-reproduction make engine-suite
```

The engine suite writes an isolated directory under `runtime/runs/` and covers
Champion train/development, common baselines, negative controls, challengers,
fee stress, entry/exit ablations, lookahead and recursive analysis. It does not
run Hyperopt after a training kill and does not open OOS.

Build the deterministic publishable bundle after verification:

```bash
make release
```

## Safety locks

`make oos` and `make canary` fail closed. OOS may be opened exactly once only
after a preregistered candidate passes every preceding train/validation,
causality, robustness, pair and statistical gate. Canary remains dry-run-only
and must never place live orders. Micro-live is outside the present evidence
and authorization stage.

GitHub publication is fail-closed and connector-mediated. The verified snapshot
is published without overwriting existing files under `fqt_rnd/` on branch
`codex/freqtrade-rnd-v741-20260817`; pull request #2 targets `main`. The local
checkout intentionally has no write remote. Never force-push and never publish
the reconstructed upstream or raw secret-bearing evidence.
