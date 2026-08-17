#!/usr/bin/env python3
"""Build the canonical portable technical-report artifact."""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load(path: str) -> Any:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def metric_row(rows: list[dict[str, Any]], fragment: str, strategy: str) -> dict[str, Any]:
    matches = [row for row in rows if fragment in row["artifact"] and row["strategy"] == strategy]
    if len(matches) != 1:
        raise ValueError(f"expected one {fragment}/{strategy}, found {len(matches)}")
    return matches[0]


def german_decimal(value: float) -> str:
    return f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def file_source(identifier: str, label: str, path: str) -> dict[str, str]:
    """Canonical provenance for a narrative sourced directly from a file."""

    return {"id": identifier, "label": label, "path": path}


def query_source(
    identifier: str,
    label: str,
    sql: str,
    description: str,
    *,
    filters: list[str] | None = None,
    metric_definitions: list[str] | None = None,
) -> dict[str, Any]:
    """Canonical provenance for rows actually selected from report_data.sqlite."""

    return {
        "id": identifier,
        "label": label,
        "path": "report/report_data.sqlite",
        "query": {
            "engine": "sqlite",
            "language": "sql",
            "sql": sql,
            "description": description,
            "tables_used": [f"report_data.{identifier.removesuffix('_query')}"],
            "filters": filters or [],
            "metric_definitions": metric_definitions or [],
        },
    }


def materialize_sqlite(datasets: dict[str, list[dict[str, Any]]]) -> Path:
    """Persist reviewed rows and return the exact SQLite source used by widgets."""

    path = ROOT / "report/report_data.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    connection = sqlite3.connect(path)
    try:
        for table, rows in datasets.items():
            if not rows:
                raise ValueError(f"report dataset {table} is empty")
            columns = list(rows[0])

            def sql_type(column: str) -> str:
                value = next((row.get(column) for row in rows if row.get(column) is not None), None)
                if isinstance(value, bool) or isinstance(value, int):
                    return "INTEGER"
                if isinstance(value, float):
                    return "REAL"
                return "TEXT"

            quoted = ", ".join(f'"{column}" {sql_type(column)}' for column in columns)
            connection.execute(f'CREATE TABLE "{table}" ({quoted})')
            placeholders = ", ".join("?" for _ in columns)
            column_sql = ", ".join(f'"{column}"' for column in columns)
            values = []
            for row in rows:
                normalized = []
                for column in columns:
                    value = row.get(column)
                    if isinstance(value, (dict, list)):
                        value = json.dumps(value, sort_keys=True, ensure_ascii=False)
                    normalized.append(value)
                values.append(normalized)
            connection.executemany(
                f'INSERT INTO "{table}" ({column_sql}) VALUES ({placeholders})',
                values,
            )
        connection.commit()
    finally:
        connection.close()
    return path


def select_rows(database: Path, sql: str) -> list[dict[str, Any]]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute(sql).fetchall()]
    finally:
        connection.close()


def main() -> int:
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    decision = load("decisions/promotion_decision.json")
    metrics = load("results/summaries/metrics_all.json")["rows"]
    gates = load("audit/gate_matrix.json")["gates"]
    data_quality = load("audit/data_quality/ohlcv_quality_summary.json")
    version = load("audit/freqtrade_version_audit.json")

    champion = metric_row(metrics, "results/champion_common_full/", "ED8")
    training = decision["identical_training_comparison"]
    training_rows = []
    for name, key in (
        ("Champion V741", "champion"),
        ("Challenger H001", "challenger_h001"),
        ("Challenger H002", "challenger_h002"),
    ):
        row = training[key]
        training_rows.append(
            {
                "strategy": name,
                "trades": row["total_trades"],
                "winrate_pct": row["winrate_pct"],
                "profit_pct": row["profit_pct"],
                "profit_factor": row["profit_factor"],
                "profit_factor_interpretation": row.get("profit_factor_state", "FINITE"),
                "wallet_drawdown_pct": row["wallet_max_drawdown_pct"],
            }
        )

    stress_specs = [
        (1, "Base fee 0.10%", "results/champion_common_full/", "ED8", "0", "0.10"),
        (2, "Fee 0.20%", "results/champion_common_fee_002/", "ED8", "0", "0.20"),
        (3, "Fee 0.30%", "results/champion_common_fee_003/", "ED8", "0", "0.30"),
        (4, "Entry delay +1", "results/champion_common_ablation/", "ED8Delay1", "1", "0.10"),
        (5, "Entry delay +2", "results/champion_common_ablation/", "ED8Delay2", "2", "0.10"),
        (6, "No custom exit", "results/champion_common_ablation/", "ED8NoCustomExitAblation", "0", "0.10"),
    ]
    stress_rows = []
    for order, scenario, fragment, strategy, delay, fee_pct in stress_specs:
        row = metric_row(metrics, fragment, strategy)
        pf = "undefined (no losses)" if row["profit_factor_state"] == "UNDEFINED_NO_LOSSES" else f"{row['profit_factor']:.2f}"
        stress_rows.append(
            {
                "order": order,
                "scenario": scenario,
                "fee_pct_per_side": fee_pct,
                "entry_delay_candles": delay,
                "trades": row["total_trades"],
                "wins": row["wins"],
                "losses": row["losses"],
                "winrate_pct": row["winrate_pct"],
                "profit_pct": row["profit_pct"],
                "profit_factor": pf,
                "wallet_drawdown_pct": row["wallet_max_drawdown_pct"],
            }
        )

    with (ROOT / "results/summaries/daily_equity.csv").open(newline="", encoding="utf-8") as handle:
        equity_rows = [
            {"date": row["date"], "strategy": row["strategy"], "equity_usdc": float(row["equity_usdc"])}
            for row in csv.DictReader(handle)
        ]
    last_equity_date = max(row["date"] for row in equity_rows)
    equity_endpoints = {
        row["strategy"]: row["equity_usdc"]
        for row in equity_rows
        if row["date"] == last_equity_date
    }

    status_priority = {
        "BLOCKIERT": 1,
        "NICHT VERIFIZIERT": 2,
        "TEILWEISE VERIFIZIERT": 3,
        "VERIFIZIERT": 4,
    }
    gate_rows = [
        {"priority": status_priority[item["status"]], **item}
        for item in gates
    ]
    gate_counts = {
        status: sum(item["status"] == status for item in gates)
        for status in status_priority
    }
    headline_rows = [
        {
            "total_trades": champion["total_trades"],
            "trades_target": 500,
            "profit_pct": champion["profit_pct"],
            "profit_target_pct": 50.0,
            "winrate_pct": champion["winrate_pct"],
            "winrate_target_pct": 80.0,
            "wallet_drawdown_pct": champion["wallet_max_drawdown_pct"],
            "drawdown_ceiling_pct": 5.0,
        }
    ]
    data_rows = [
        {
            "rows": data_quality["row_count"],
            "first": data_quality["first_timestamp_utc"],
            "last": data_quality["last_timestamp_utc"],
            "gaps": data_quality["gap_count"],
            "duplicates": data_quality["duplicate_timestamps"],
            "complete_days": data_quality["complete_calendar_days"],
            "partial_days": data_quality["partial_calendar_days"],
            "sha256": data_quality["sha256"],
        }
    ]

    report_queries = {
        "headline": "SELECT total_trades, trades_target, profit_pct, profit_target_pct, winrate_pct, winrate_target_pct, wallet_drawdown_pct, drawdown_ceiling_pct FROM headline",
        "training": "SELECT strategy, trades, winrate_pct, profit_pct, profit_factor, profit_factor_interpretation, wallet_drawdown_pct FROM training ORDER BY strategy",
        "stress": "SELECT * FROM stress ORDER BY \"order\"",
        "equity": "SELECT date, strategy, equity_usdc FROM equity ORDER BY date, strategy",
        "gates": "SELECT priority, gate, status, decision, evidence FROM gates ORDER BY priority, gate",
        "data_quality": "SELECT rows, first, last, gaps, duplicates, complete_days, partial_days, sha256 FROM data_quality",
    }
    database = materialize_sqlite(
        {
            "headline": headline_rows,
            "training": training_rows,
            "stress": stress_rows,
            "equity": equity_rows,
            "gates": gate_rows,
            "data_quality": data_rows,
        }
    )
    headline_rows = select_rows(database, report_queries["headline"])
    training_rows = select_rows(database, report_queries["training"])
    stress_rows = select_rows(database, report_queries["stress"])
    equity_rows = select_rows(database, report_queries["equity"])
    gate_rows = select_rows(database, report_queries["gates"])
    data_rows = select_rows(database, report_queries["data_quality"])

    sources = [
        query_source(
            "headline_query",
            "Headline metrics query",
            report_queries["headline"],
            "Selects the Champion development result and explicit promotion thresholds.",
            filters=["Binance Spot; BTC/USDC; 1m; long-only", "Development window only; frozen OOS excluded"],
            metric_definitions=[
                "Net profit % = (final wallet - 1,000 USDC) / 1,000 USDC * 100 after modeled fees.",
                "Winrate % = winning closed trades / all closed trades * 100.",
                "Wallet drawdown % = maximum peak-to-trough decline of simulated minute wallet equity.",
            ],
        ),
        query_source("training_query", "Training comparison query", report_queries["training"], "Selects the identical-contract Champion and Challenger training rows."),
        query_source(
            "stress_query",
            "Stress comparison query",
            report_queries["stress"],
            "Selects common-capital fee, entry-delay and exit-ablation results.",
            metric_definitions=["Profit Factor = gross winning profit / absolute gross losing profit; undefined when there are no losing trades."],
        ),
        query_source(
            "equity_query",
            "Daily equity query",
            report_queries["equity"],
            "Selects deterministic daily endpoints for Champion, cash and buy-and-hold.",
            filters=["2026-01-01 <= date <= 2026-05-01"],
            metric_definitions=["Daily equity = final per-minute sum of every wallet currency's total_quote value for each UTC calendar date."],
        ),
        query_source("gates_query", "Gate matrix query", report_queries["gates"], "Selects every gate ordered from blocked to verified."),
        query_source("data_quality_query", "OHLCV quality query", report_queries["data_quality"], "Selects structural BTC/USDC 1m data-quality aggregates."),
        file_source("promotion", "Promotion decision", "decisions/promotion_decision.json"),
        file_source("metrics", "Normalized Freqtrade metrics", "results/summaries/metrics_all.json"),
        file_source("equity", "Daily Freqtrade wallet equity", "results/summaries/daily_equity.csv"),
        file_source("gates", "Research gate matrix", "audit/gate_matrix.json"),
        file_source("contract", "Frozen research contract", "contracts/research_contract_v1.json"),
        file_source("quality", "BTC/USDC OHLCV quality audit", "audit/data_quality/ohlcv_quality_summary.json"),
        file_source("determinism", "Exact reproduction audit", "audit/deterministic_reproduction.json"),
        file_source("causality", "Lookahead and recursive summary", "audit/causality_summary.json"),
        file_source("version", "Freqtrade version audit", "audit/freqtrade_version_audit.json"),
        file_source("statistics", "Bootstrap and Monte Carlo diagnostics", "results/summaries/statistical_stress.json"),
        file_source("secrets", "Secret scan", "audit/secret_scan.json"),
        file_source("github", "GitHub publication status", "audit/github_publication.json"),
    ]

    title = "Freqtrade R&D Audit — V741 bleibt ein historischer Champion"
    manifest = {
        "version": 1,
        "surface": "report",
        "title": title,
        "description": "Technischer Champion-Challenger-Audit für Binance Spot, BTC/USDC, Long-only, 1m.",
        "generatedAt": generated_at,
        "filters": [],
        "cards": [
            {
                "id": "trades_card",
                "description": "Geschlossene Trades im Entwicklungsfenster gegenüber dem Promotionsziel.",
                "dataset": "headline",
                "sourceId": "headline_query",
                "metrics": [
                    {"label": "Trades", "field": "total_trades", "format": "number"},
                    {"label": "Ziel >", "field": "trades_target", "format": "number"},
                ],
            },
            {
                "id": "profit_card",
                "description": "Nettoprofit im Entwicklungsfenster; Prozentwert auf 1.000 USDC Startkapital.",
                "dataset": "headline",
                "sourceId": "headline_query",
                "metrics": [
                    {"label": "Nettoprofit", "field": "profit_pct", "format": "number", "unit": "%"},
                    {"label": "Ziel >", "field": "profit_target_pct", "format": "number", "unit": "%"},
                ],
            },
            {
                "id": "winrate_card",
                "description": "Gewinntrades geteilt durch geschlossene Trades; Stichprobe n=20.",
                "dataset": "headline",
                "sourceId": "headline_query",
                "metrics": [
                    {"label": "Winrate", "field": "winrate_pct", "format": "number", "unit": "%"},
                    {"label": "Ziel >", "field": "winrate_target_pct", "format": "number", "unit": "%"},
                ],
            },
            {
                "id": "drawdown_card",
                "description": "Maximaler Wallet-Drawdown der simulierten Minuten-Equity.",
                "dataset": "headline",
                "sourceId": "headline_query",
                "metrics": [
                    {"label": "Wallet-DD", "field": "wallet_drawdown_pct", "format": "number", "unit": "%"},
                    {"label": "Obergrenze <", "field": "drawdown_ceiling_pct", "format": "number", "unit": "%"},
                ],
            },
        ],
        "charts": [
            {
                "id": "equity_chart",
                "title": "Tägliche simulierte Equity",
                "subtitle": "Summe aller Wallet-Währungen; 1.000 USDC Startkapital; 121 UTC-Tagesendpunkte je Serie.",
                "type": "line",
                "dataset": "equity",
                "sourceId": "equity_query",
                "valueFormat": "number",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Datum"},
                    "y": {"field": "equity_usdc", "type": "quantitative", "label": "Equity (USDC)"},
                    "color": {"field": "strategy", "type": "nominal", "label": "Vergleich"},
                    "tooltip": [
                        {"field": "strategy", "type": "nominal", "label": "Serie"},
                        {"field": "equity_usdc", "type": "quantitative", "label": "Equity", "format": "number"},
                    ],
                },
            },
            {
                "id": "training_profit_chart",
                "title": "Nettoprofit im identischen Trainingsvertrag",
                "subtitle": "BTC/USDC 1m, 1.000 USDC, 0,10% Gebühr je Seite, 1. Januar bis 1. März 2026.",
                "type": "bar",
                "dataset": "training",
                "sourceId": "training_query",
                "valueFormat": "number",
                "encodings": {
                    "x": {"field": "strategy", "type": "nominal", "label": "Strategie"},
                    "y": {"field": "profit_pct", "type": "quantitative", "label": "Nettoprofit (%)"},
                    "tooltip": [
                        {"field": "trades", "type": "quantitative", "label": "Trades", "format": "number"},
                        {"field": "winrate_pct", "type": "quantitative", "label": "Winrate (%)", "format": "number"},
                    ],
                },
            },
        ],
        "tables": [
            {
                "id": "training_table",
                "title": "Champion-Challenger auf identischem Training",
                "subtitle": "Gleiche Daten, Pair-, Gebühren-, Wallet-, Stake- und Parallelpositionsparameter.",
                "dataset": "training",
                "sourceId": "training_query",
                "defaultSort": {"field": "profit_pct", "direction": "desc"},
                "columns": [
                    {"field": "strategy", "label": "Strategie", "type": "text"},
                    {"field": "trades", "label": "Trades", "format": "number"},
                    {"field": "winrate_pct", "label": "Winrate (%)", "format": "number"},
                    {"field": "profit_pct", "label": "Profit (%)", "format": "number", "semantic": "movement"},
                    {"field": "profit_factor", "label": "PF-Rohwert", "format": "number"},
                    {"field": "profit_factor_interpretation", "label": "PF-Interpretation", "type": "text"},
                    {"field": "wallet_drawdown_pct", "label": "Wallet-DD (%)", "format": "number"},
                ],
            },
            {
                "id": "stress_table",
                "title": "Gebühren-, Delay- und Exit-Stress",
                "subtitle": "Entwicklungsfenster; alle Zeilen 1.000 USDC, unlimited Stake und max_open_trades=1.",
                "dataset": "stress",
                "sourceId": "stress_query",
                "defaultSort": {"field": "order", "direction": "asc"},
                "columns": [
                    {"field": "order", "label": "#", "format": "number"},
                    {"field": "scenario", "label": "Szenario", "type": "text"},
                    {"field": "trades", "label": "Trades", "format": "number"},
                    {"field": "wins", "label": "Wins", "format": "number"},
                    {"field": "losses", "label": "Losses", "format": "number"},
                    {"field": "winrate_pct", "label": "Winrate (%)", "format": "number"},
                    {"field": "profit_pct", "label": "Profit (%)", "format": "number", "semantic": "movement"},
                    {"field": "profit_factor", "label": "Profit Factor", "type": "text"},
                    {"field": "wallet_drawdown_pct", "label": "Wallet-DD (%)", "format": "number"},
                ],
            },
            {
                "id": "gate_table",
                "title": "Vollständige Forschungs-Gate-Matrix",
                "subtitle": "31 Gates; blockierte und nicht verifizierte Punkte stehen zuerst.",
                "dataset": "gates",
                "sourceId": "gates_query",
                "defaultSort": {"field": "priority", "direction": "asc"},
                "columns": [
                    {"field": "priority", "label": "Priorität", "format": "number"},
                    {"field": "gate", "label": "Gate", "type": "text"},
                    {"field": "status", "label": "Status", "type": "text"},
                    {"field": "decision", "label": "Entscheidung / Lücke", "type": "text"},
                    {"field": "evidence", "label": "Artefakt", "type": "text"},
                ],
            },
            {
                "id": "data_table",
                "title": "BTC/USDC-1m-Datensatz",
                "subtitle": "Struktur- und Kontinuitätsprüfung des einzigen zulässigen USDC-Pairs.",
                "dataset": "data_quality",
                "sourceId": "data_quality_query",
                "defaultSort": {"field": "rows", "direction": "desc"},
                "columns": [
                    {"field": "rows", "label": "Zeilen", "format": "number"},
                    {"field": "first", "label": "Erste Kerze", "type": "text"},
                    {"field": "last", "label": "Letzte Kerze", "type": "text"},
                    {"field": "gaps", "label": "Lücken", "format": "number"},
                    {"field": "duplicates", "label": "Duplikate", "format": "number"},
                    {"field": "complete_days", "label": "Volle Tage", "format": "number"},
                    {"field": "partial_days", "label": "Teiltage", "format": "number"},
                    {"field": "sha256", "label": "SHA-256", "type": "text"},
                ],
            },
        ],
        "sources": sources,
        "blocks": [
            {"id": "title", "type": "markdown", "body": f"# {title}"},
            {
                "id": "technical_summary",
                "type": "markdown",
                "sourceId": "promotion",
                "body": (
                    "## Technisches Ergebnis\n\n"
                    "- **Keine Promotion:** V741 bleibt unverändert der historische Champion; es gibt keinen Deployment-Champion.\n"
                    "- **Entwicklungsresultat:** 20 Trades, 100% Winrate, +26,24% auf 1.000 USDC und 1,91% Wallet-Drawdown. "
                    "Tradezahl, Aktivität und Profitziel werden verfehlt; der Profit Factor ist bei null Verlusten nicht definiert.\n"
                    "- **Challenger falsifiziert:** H001 verliert 74,18%, H002 45,07% auf identischem Training.\n"
                    "- **Folge:** Validation, Frozen OOS, Canary und Live bleiben geschlossen."
                ),
            },
            {"id": "metrics_strip", "type": "metric-strip", "cardIds": ["trades_card", "profit_card", "winrate_card", "drawdown_card"]},
            {
                "id": "equity_finding",
                "type": "markdown",
                "sourceId": "equity",
                "body": (
                    "## Die Backtest-Equity steigt, aber nur auf einem selektierten Pair\n\n"
                    f"Der letzte tägliche Mark-to-Market-Punkt liegt für V741 bei {german_decimal(equity_endpoints['Champion V741'])} USDC, "
                    f"für Cash bei {german_decimal(equity_endpoints['Cash'])} USDC und für Buy-and-Hold bei {german_decimal(equity_endpoints['Buy-and-hold'])} USDC. "
                    "Die Kurve zeigt damit einen historischen Mehrertrag in dieser Simulation; sie belegt weder Pair-Generalisation noch künftige Ausführbarkeit."
                ),
            },
            {"id": "equity_visual", "type": "chart", "chartId": "equity_chart"},
            {
                "id": "training_finding",
                "type": "markdown",
                "sourceId": "promotion",
                "body": (
                    "## Beide Challenger scheitern bereits im Training\n\n"
                    "Unter identischem Vertrag erreicht V741 +15,25% mit 13 Trades. H001 erzeugt zwar 685 Trades, verliert aber 74,18%; "
                    "H002 verbessert die Winrate auf 67,70%, verliert dennoch 45,07%. Daher wäre jede weitere Öffnung der Validation ergebnisgetriebenes Tuning."
                ),
            },
            {"id": "training_visual", "type": "chart", "chartId": "training_profit_chart"},
            {"id": "training_detail", "type": "table", "tableId": "training_table"},
            {
                "id": "stress_finding",
                "type": "markdown",
                "sourceId": "metrics",
                "body": (
                    "## Kostenstress zerstört die Zielqualität\n\n"
                    "Bei 0,20% und 0,30% Gebühr je Seite sinkt die Winrate auf jeweils 78,95%, der Nettoprofit auf 13,97% bzw. 9,44% "
                    "und der Profit Factor auf 3,69 bzw. 2,51. Delay +1/+2 bleibt positiv, basiert aber weiterhin nur auf 20 Trades."
                ),
            },
            {"id": "stress_detail", "type": "table", "tableId": "stress_table"},
            {
                "id": "scope_definitions",
                "type": "markdown",
                "sourceId": "contract",
                "body": (
                    "## Scope und Metrikdefinitionen\n\n"
                    "Der Vergleich gilt ausschließlich für Binance Spot, BTC/USDC, Long-only, 1-Minuten-Kerzen, unlimited Stake und genau eine offene Position. "
                    "Profit ist Nettoprofit nach modellierter Gebühr; Wallet-Drawdown verwendet die simulierte Minuten-Equity. "
                    "Der Frozen-OOS-Bereich ist 2.–9. Mai 2026 (Ende exklusiv) und bleibt unangetastet."
                ),
            },
            {"id": "data_detail", "type": "table", "tableId": "data_table"},
            {
                "id": "methodology",
                "type": "markdown",
                "body": (
                    "## Methodik und Reproduzierbarkeit\n\n"
                    "Der eingefrorene Champion wurde über SHA-256 fixiert. Die historische 20-Trade-Liste und alle ausgewählten Kennzahlen wurden byte-/wertgleich reproduziert; "
                    "ein bewusst aufbewahrter Fehlversuch führte die Abweichung auf BTC-Mengenpräzision zurück. Statische Causality-Prüfung, Prefix-Test, "
                    "Vorminuten-Signal/Folgkerzen-Open-Prüfung, Freqtrade-Lookahead, Recursive, Baselines, Negativkontrollen, Gebühren, Delay, Ablationen sowie bedingte Bootstrap-/Monte-Carlo-Diagnostik sind artefaktgebunden."
                ),
            },
            {
                "id": "version_note",
                "type": "markdown",
                "sourceId": "version",
                "body": (
                    "## Version und Kompatibilität\n\n"
                    f"Die lokale Engine ist Freqtrade {version['local_runtime']['freqtrade']} auf Commit {version['local_runtime']['git_commit'][:12]}, "
                    f"Python {version['local_runtime']['python']} und CCXT {version['local_runtime']['ccxt']}. "
                    f"Die am {version['official_reference']['release_observed_at_utc']} auf der offiziellen Release-Seite als aktuell markierte Version ist "
                    f"{version['official_reference']['observed_latest_release']}. Die eingefrorene ältere Engine reproduziert den historischen "
                    "2026.5.1-Lauf exakt; Kompatibilität mit der aktuellen Version, Exchange-Verhalten und Live-Betrieb sind dadurch nicht bewiesen."
                ),
            },
            {
                "id": "gate_finding",
                "type": "markdown",
                "sourceId": "gates",
                "body": (
                    "## Die Mehrzahl der Promotions-Gates ist noch offen\n\n"
                    f"Von {len(gates)} Gates sind {gate_counts['VERIFIZIERT']} verifiziert, "
                    f"{gate_counts['TEILWEISE VERIFIZIERT']} teilweise verifiziert, "
                    f"{gate_counts['NICHT VERIFIZIERT']} nicht verifiziert und {gate_counts['BLOCKIERT']} blockiert. "
                    "Die kritischsten Stopper sind Recursive-Stabilität, fehlendes historisches 30-Pair-USDC-Universum, "
                    "fehlende Pair-Holdouts und das versiegelte OOS."
                ),
            },
            {"id": "gate_detail", "type": "table", "tableId": "gate_table"},
            {
                "id": "limitations",
                "type": "markdown",
                "sourceId": "statistics",
                "body": (
                    "## Grenzen, Unsicherheit und robuste Gegenbefunde\n\n"
                    "Die Auswahlhistorie ist groß und nicht vollständig als unabhängige Testfamilie rekonstruierbar; Multiple-Testing-Korrekturen bleiben daher sensitivitätsbasiert. "
                    "Bootstrap resampelt eine selektierte 20-Trade-Stichprobe und entfernt keinen Selection Bias."
                ),
            },
            {
                "id": "causality_limit",
                "type": "markdown",
                "sourceId": "causality",
                "body": (
                    "**Causality-Grenze:** Lookahead prüfte nur zehn ausgelöste Signale. Recursive zeigt bei "
                    "startup_candle_count=1600 materielle Abweichungen in langen EMA-/Quantilfeatures."
                ),
            },
            {
                "id": "universe_limit",
                "type": "markdown",
                "sourceId": "quality",
                "body": "**Universumsgrenze:** Nur BTC/USDC ist vorhanden; Survivorship und Pair-Generalisation sind blockiert.",
            },
            {
                "id": "next_steps",
                "type": "markdown",
                "body": (
                    "## Empfohlene nächste Arbeitspakete\n\n"
                    "1. Historisches Binance-USDC-Universum inklusive Listings/Delistings und mindestens 30 vollständige 1m-Pairs beschaffen und hash-frieren.\n"
                    "2. Recursive-Ursache beseitigen oder einen nachweislich stabilen Startup-Wert festlegen; danach Lookahead-Abdeckung über alle Entry-/Exit-Tags erhöhen.\n"
                    "3. Einen neuen, vorregistrierten Challenger ausschließlich auf Training entwickeln; Kill-Kriterien automatisiert anwenden.\n"
                    "4. Erst nach Train-Pass Multi-Seed-Hyperopt, Plateau-Test, Validation, Rolling/Anchored-WF und Pair-Holdouts ausführen.\n"
                    "5. Frozen OOS genau einmal öffnen; nur bei vollständigem Gate-Pass einen mehrwöchigen Dry-run-Canary starten."
                ),
            },
            {
                "id": "further_questions",
                "type": "markdown",
                "body": (
                    "## Offene Fragen\n\n"
                    "- Kann ein historischer Binance-USDC-Pair-Snapshot mit Delisting-Historie bereitgestellt werden?\n"
                    "- Soll der nächste Challenger primär Aktivität, Kostenrobustheit oder Pair-Generalisation optimieren?"
                ),
            },
        ],
    }
    artifact = {
        "surface": "report",
        "manifest": manifest,
        "snapshot": {
            "version": 1,
            "generatedAt": generated_at,
            "status": "partial",
            "datasets": {
                "headline": headline_rows,
                "training": training_rows,
                "stress": stress_rows,
                "equity": equity_rows,
                "gates": gate_rows,
                "data_quality": data_rows,
            },
            "accessIssues": [
                {"id": "pair_universe_missing", "dataset": "pair_universe", "message": "Only BTC/USDC 1m is available; pair holdouts and survivorship audit are blocked."},
            ],
        },
        "sources": sources,
        "package_info": {"originUrl": "artifact://fqt-rnd-v741-audit", "controls": {"edit": False, "refresh": False}},
    }
    report_dir = ROOT / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "artifact.json").write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    source_notes = {
        "audience": "technical",
        "delivery_mode": "html",
        "report_job": {
            "question": "Is any strategy promotable under the frozen Freqtrade research contract?",
            "decision_useful_answer": decision["decision"],
            "scope": training["contract"],
            "success_criteria": list(decision["promotion_targets_pass"]),
        },
        "required_structure_mapping": {
            "technical_summary": "Technisches Ergebnis",
            "key_findings": ["Equity", "Training comparison", "Stress"],
            "scope_definitions": "Scope und Metrikdefinitionen",
            "methodology": "Methodik und Reproduzierbarkeit",
            "limitations": "Grenzen, Unsicherheit und robuste Gegenbefunde",
            "recommended_next_steps": "Empfohlene nächste Arbeitspakete",
            "further_questions": "Offene Fragen",
        },
        "chart_map": [
            {
                "section": "Equity finding",
                "question": "How did simulated capital evolve against cash and buy-and-hold?",
                "family": "Trend",
                "type": "line",
                "fields": ["date", "strategy", "equity_usdc"],
                "data_sufficiency": "121 daily points per series",
                "palette_policy": "relaxed multi-category; three directly named series",
                "claim": "V741 ends above both controls in the selected backtest",
            },
            {
                "section": "Training finding",
                "question": "Which strategy generated net profit under the identical train contract?",
                "family": "Comparison",
                "type": "bar",
                "fields": ["strategy", "profit_pct"],
                "data_sufficiency": "three intentional, fully labelled candidates",
                "palette_policy": "single-root preferred; zero baseline",
                "claim": "both challengers are negative on training",
            },
        ],
        "omissions": [
            "No OOS visual: the frozen OOS was correctly not opened.",
            "No pair comparison visual: only BTC/USDC exists.",
            "No finite Profit-Factor card: the base run has zero losses, so PF is undefined rather than infinite.",
        ],
    }
    (report_dir / "source_notes.json").write_text(json.dumps(source_notes, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"artifact": "report/artifact.json", "blocks": len(manifest["blocks"]), "datasets": len(artifact["snapshot"]["datasets"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
