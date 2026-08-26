#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path.cwd()
WORK = ROOT / "fqt_v25_work"
OUT = ROOT / "fqt_v25_results"
USERDIR = WORK / "user_data"
STRATDIR = USERDIR / "strategies"
DATADIR = USERDIR / "data" / "binance"
RESULTDIR = USERDIR / "backtest_results"
LOGDIR = OUT / "logs"
TABLEDIR = OUT / "tables"
EVIDDIR = OUT / "evidence"
FINALDIR = OUT / "final"
for p in [WORK, OUT, STRATDIR, DATADIR, RESULTDIR, LOGDIR, TABLEDIR, EVIDDIR, FINALDIR]:
    p.mkdir(parents=True, exist_ok=True)

FREQTRADE_COMMIT = "77cabd291fa656ec6a1d237cfa524ee792133d89"
DEV_RANGE = "20260101-20260501"
KNOWN_RANGE = "20260501-20260623"
TRAIN_RANGE = "20260101-20260623"
OOS_RANGE = "20260623-20260812"
FULL_RANGE = "20260101-20260812"
FOLDS = [
    ("F1_JAN_FEB", "20260101-20260301"),
    ("F2_MAR_APR", "20260301-20260501"),
    ("F3_MAY_JUN22", "20260501-20260623"),
]

ORIGINAL_PAIRS = [
    "BTC/USDC", "ETH/USDC", "SOL/USDC", "XRP/USDC", "BNB/USDC",
    "DOGE/USDC", "ENA/USDC", "HBAR/USDC", "LTC/USDC", "AAVE/USDC",
    "XPL/USDC", "LINK/USDC", "BCH/USDC", "DOT/USDC", "PUMP/USDC",
    "TRX/USDC", "AVAX/USDC", "UNI/USDC", "ARB/USDC", "PENDLE/USDC",
    "SYRUP/USDC", "ALGO/USDC", "ZK/USDC", "WLFI/USDC", "FIL/USDC",
    "ASTER/USDC", "SHIB/USDC", "SEI/USDC", "DASH/USDC", "2Z/USDC",
    "ATOM/USDC",
]
REPLACEMENT_POOL = [
    "ADA/USDC", "SUI/USDC", "XLM/USDC", "PEPE/USDC", "NEAR/USDC",
    "OP/USDC", "ETC/USDC", "ICP/USDC", "POL/USDC", "WIF/USDC",
    "BONK/USDC", "JUP/USDC", "FET/USDC", "INJ/USDC", "RENDER/USDC",
    "TIA/USDC", "CRV/USDC", "GRT/USDC", "VET/USDC", "IMX/USDC",
    "SAND/USDC", "MANA/USDC", "RUNE/USDC", "APT/USDC", "AR/USDC",
]

CANDIDATES = [
    "M4PioneerValidationV14",
    "M4PioneerOOSV25NoVWAP",
    "M4PioneerOOSV25FeeFloor",
    "M4PioneerOOSV25NoVWAPFeeFloor",
    "M4PioneerOOSV25PathStake",
    "M4PioneerOOSV25NoVWAPPathStake",
]


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def dump(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def run(cmd: list[str], label: str, cwd: Path | None = None, timeout: int = 7200, allow_fail: bool = False) -> subprocess.CompletedProcess[str]:
    started = now()
    cp = subprocess.run(
        cmd,
        cwd=cwd or ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        env={**os.environ, "PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"},
    )
    (LOGDIR / f"{label}.log").write_text(cp.stdout, encoding="utf-8", errors="replace")
    dump(EVIDDIR / f"{label}_receipt.json", {
        "label": label, "started": started, "finished": now(), "command": cmd,
        "exit_code": cp.returncode, "log_sha256": sha256(LOGDIR / f"{label}.log"),
    })
    if cp.returncode and not allow_fail:
        raise RuntimeError(f"{label} failed rc={cp.returncode}")
    return cp


def fetch(url: str, dest: Path, retries: int = 5) -> bool:
    if dest.exists() and dest.stat().st_size > 0:
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "FQT-V25/1.0"})
            with urllib.request.urlopen(req, timeout=90) as r, dest.with_suffix(dest.suffix + ".part").open("wb") as f:
                shutil.copyfileobj(r, f)
            dest.with_suffix(dest.suffix + ".part").replace(dest)
            return True
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
            dest.with_suffix(dest.suffix + ".part").unlink(missing_ok=True)
            time.sleep(min(2 ** attempt, 16))
    return False


def locate_parent() -> tuple[Path, Path | None]:
    py_candidates = [p for p in ROOT.rglob("M4PioneerValidationV14*.py") if "fqt_v25_work" not in str(p)]
    json_candidates = [p for p in ROOT.rglob("config_M4PioneerValidationV14*.json") if "fqt_v25_work" not in str(p)]
    if not py_candidates:
        raise FileNotFoundError("M4PioneerValidationV14 parent strategy missing from project branch")
    py_candidates.sort(key=lambda p: ("FINAL_V23" not in p.name, len(str(p))))
    json_candidates.sort(key=lambda p: ("FINAL_V23" not in p.name, len(str(p))))
    return py_candidates[0], json_candidates[0] if json_candidates else None


def materialize_pair(pair: str) -> bool:
    symbol = pair.replace("/", "")
    target = DATADIR / f"{pair.replace('/', '_')}-1m.parquet"
    if target.exists() and target.stat().st_size > 0:
        return True
    raw_dir = WORK / "raw" / symbol
    frames: list[pd.DataFrame] = []
    periods = [(2025, 12)] + [(2026, m) for m in range(1, 8)]
    for year, month in periods:
        name = f"{symbol}-1m-{year:04d}-{month:02d}.zip"
        url = f"https://data.binance.vision/data/spot/monthly/klines/{symbol}/1m/{name}"
        zpath = raw_dir / name
        if not fetch(url, zpath):
            return False
        try:
            with zipfile.ZipFile(zpath) as zf:
                member = [n for n in zf.namelist() if n.endswith(".csv")][0]
                frame = pd.read_csv(zf.open(member), header=None)
        except Exception:
            return False
        frames.append(frame)
    for day in range(1, 12):
        name = f"{symbol}-1m-2026-08-{day:02d}.zip"
        url = f"https://data.binance.vision/data/spot/daily/klines/{symbol}/1m/{name}"
        zpath = raw_dir / name
        if not fetch(url, zpath):
            return False
        try:
            with zipfile.ZipFile(zpath) as zf:
                member = [n for n in zf.namelist() if n.endswith(".csv")][0]
                frame = pd.read_csv(zf.open(member), header=None)
        except Exception:
            return False
        frames.append(frame)
    df = pd.concat(frames, ignore_index=True)
    df = df.iloc[:, :6]
    df.columns = ["date", "open", "high", "low", "close", "volume"]
    ts = pd.to_numeric(df["date"], errors="coerce")
    unit = "us" if float(ts.dropna().median()) > 1e14 else "ms"
    df["date"] = pd.to_datetime(ts, unit=unit, utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna().drop_duplicates("date").sort_values("date").reset_index(drop=True)
    start = pd.Timestamp("2025-12-31T00:00:00Z")
    end = pd.Timestamp("2026-08-12T00:00:00Z")
    df = df[(df["date"] >= start) & (df["date"] < end)].copy()
    if len(df) < 300000 or not df["date"].is_monotonic_increasing:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(target, index=False)
    dump(EVIDDIR / "data" / f"{symbol}.json", {
        "pair": pair, "rows": len(df), "first": df["date"].iloc[0], "last": df["date"].iloc[-1],
        "duplicates": int(df["date"].duplicated().sum()), "sha256": sha256(target),
        "zero_volume_ratio": float((df["volume"] == 0).mean()),
    })
    return True


def fallback_config() -> dict[str, Any]:
    return {
        "max_open_trades": 1, "stake_currency": "USDC", "stake_amount": "unlimited",
        "tradable_balance_ratio": 0.99, "fiat_display_currency": "USD", "dry_run": True,
        "dry_run_wallet": 1000, "cancel_open_orders_on_exit": False, "trading_mode": "spot",
        "margin_mode": "", "timeframe": "1m", "dataformat_ohlcv": "parquet",
        "exchange": {"name": "binance", "key": "", "secret": "", "ccxt_config": {}, "ccxt_async_config": {}, "pair_whitelist": [], "pair_blacklist": []},
        "pairlists": [{"method": "StaticPairList"}],
        "entry_pricing": {"price_side": "same", "use_order_book": False, "order_book_top": 1, "price_last_balance": 0.0, "check_depth_of_market": {"enabled": False, "bids_to_ask_delta": 1}},
        "exit_pricing": {"price_side": "same", "use_order_book": False, "order_book_top": 1},
        "order_types": {"entry": "limit", "exit": "limit", "emergency_exit": "market", "force_entry": "market", "force_exit": "market", "stoploss": "market", "stoploss_on_exchange": False},
        "unfilledtimeout": {"entry": 10, "exit": 10, "exit_timeout_count": 0, "unit": "minutes"},
        "telegram": {"enabled": False, "token": "", "chat_id": ""},
        "api_server": {"enabled": False, "listen_ip_address": "127.0.0.1", "listen_port": 8080, "verbosity": "error", "enable_openapi": False, "jwt_secret_key": "", "ws_token": "", "CORS_origins": [], "username": "", "password": ""},
        "initial_state": "stopped", "force_entry_enable": False, "internals": {"process_throttle_secs": 5},
    }


def make_config(template: dict[str, Any], pairs: list[str], name: str, max_open: int = 1, wallet: float = 1000, stake: Any = "unlimited") -> Path:
    cfg = json.loads(json.dumps(template))
    cfg["max_open_trades"] = max_open
    cfg["stake_currency"] = "USDC"
    cfg["stake_amount"] = stake
    cfg["dry_run_wallet"] = wallet
    cfg["dry_run"] = True
    cfg["initial_state"] = "stopped"
    cfg["trading_mode"] = "spot"
    cfg["dataformat_ohlcv"] = "parquet"
    cfg.setdefault("exchange", {})["name"] = "binance"
    cfg["exchange"]["key"] = ""
    cfg["exchange"]["secret"] = ""
    cfg["exchange"]["pair_whitelist"] = pairs
    cfg["exchange"]["pair_blacklist"] = []
    cfg["pairlists"] = [{"method": "StaticPairList"}]
    cfg.setdefault("telegram", {})["enabled"] = False
    cfg.setdefault("api_server", {})["enabled"] = False
    path = WORK / "configs" / f"{name}.json"
    dump(path, cfg)
    return path


def parse_result(path: Path, strategy: str) -> dict[str, Any]:
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n.endswith(".json") and "config" not in n.lower()]
        if not names:
            raise RuntimeError(f"No result json in {path}")
        obj = json.loads(zf.read(names[0]))
    block = obj.get("strategy", {}).get(strategy)
    if block is None and obj.get("strategy"):
        block = next(iter(obj["strategy"].values()))
    if block is None:
        raise RuntimeError(f"Strategy {strategy} missing in {path}")
    trades = block.get("trades", [])
    wins = int(block.get("wins", sum(float(t.get("profit_abs", 0)) > 0 for t in trades)))
    losses = int(block.get("losses", sum(float(t.get("profit_abs", 0)) < 0 for t in trades)))
    draws = int(block.get("draws", len(trades) - wins - losses))
    pf = block.get("profit_factor")
    if pf is None:
        gp = sum(max(float(t.get("profit_abs", 0)), 0) for t in trades)
        gl = -sum(min(float(t.get("profit_abs", 0)), 0) for t in trades)
        pf = gp / gl if gl else 999.0
    return {
        "strategy": strategy, "total_trades": int(block.get("total_trades", len(trades))),
        "wins": wins, "draws": draws, "losses": losses,
        "winrate_pct": 100.0 * wins / max(len(trades), 1),
        "profit_usdc": float(block.get("profit_total_abs", sum(float(t.get("profit_abs", 0)) for t in trades))),
        "profit_pct": 100.0 * float(block.get("profit_total", 0)),
        "profit_factor": float(pf),
        "max_drawdown_pct": 100.0 * float(block.get("max_drawdown_account", block.get("max_drawdown", 0))),
        "starting_balance": float(block.get("starting_balance", 1000)),
        "final_balance": float(block.get("final_balance", 1000 + float(block.get("profit_total_abs", 0)))),
        "trades": trades,
        "results_per_pair": block.get("results_per_pair", []),
        "result_sha256": sha256(path),
    }


def backtest(template: dict[str, Any], pairs: list[str], strategy: str, timerange: str, label: str, fee: float = 0.001, max_open: int = 1, wallet: float = 1000, stake: Any = "unlimited", export: str = "trades", allow_fail: bool = False) -> dict[str, Any] | None:
    cfg = make_config(template, pairs, label, max_open=max_open, wallet=wallet, stake=stake)
    outzip = RESULTDIR / f"{label}.zip"
    outzip.unlink(missing_ok=True)
    cmd = [sys.executable, "-m", "freqtrade", "backtesting", "-c", str(cfg), "--strategy-path", str(STRATDIR), "-s", strategy, "-i", "1m", "--timerange", timerange, "--fee", str(fee), "--data-format-ohlcv", "parquet", "--export", export, "--export-filename", str(outzip), "--cache", "none", "--breakdown", "month", "--no-color"]
    cp = run(cmd, label, timeout=10800, allow_fail=allow_fail)
    if cp.returncode or not outzip.exists():
        return None
    result = parse_result(outzip, strategy)
    dump(EVIDDIR / "results" / f"{label}.json", {k: v for k, v in result.items() if k != "trades"})
    return result


def pair_metrics_from_trades(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for t in trades:
        pair = t.get("pair", "UNKNOWN")
        row = out.setdefault(pair, {"pair": pair, "trades": 0, "wins": 0, "losses": 0, "profit_usdc": 0.0, "gross_profit": 0.0, "gross_loss": 0.0})
        p = float(t.get("profit_abs", 0))
        row["trades"] += 1
        row["wins"] += int(p > 0)
        row["losses"] += int(p < 0)
        row["profit_usdc"] += p
        row["gross_profit"] += max(p, 0)
        row["gross_loss"] += -min(p, 0)
    for row in out.values():
        row["winrate_pct"] = 100 * row["wins"] / max(row["trades"], 1)
        row["profit_factor"] = row["gross_profit"] / row["gross_loss"] if row["gross_loss"] else 999.0
    return out


def write_candidate_strategy(parent_path: Path) -> Path:
    shutil.copy2(parent_path, STRATDIR / "M4PioneerValidationV14.py")
    code = r'''from __future__ import annotations
import numpy as np
import pandas as pd
from pandas import DataFrame
from M4PioneerValidationV14 import M4PioneerValidationV14

class _V25Base(M4PioneerValidationV14):
    v25_block_vwap = False
    v25_fee_floor = False
    v25_stake_policy = "parent"

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_indicators(dataframe, metadata)
        high = pd.to_numeric(df["high"], errors="coerce")
        low = pd.to_numeric(df["low"], errors="coerce")
        close = pd.to_numeric(df["close"], errors="coerce")
        prev = close.shift(1)
        tr = pd.concat([(high-low).abs(), (high-prev).abs(), (low-prev).abs()], axis=1).max(axis=1)
        df["v25_atr_pct"] = tr.rolling(14, min_periods=14).mean() / close.replace(0, np.nan)
        df["v25_range60_pct"] = high.rolling(60, min_periods=60).max() / low.rolling(60, min_periods=60).min().replace(0, np.nan) - 1.0
        return df

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        active = pd.to_numeric(df.get("enter_long", 0), errors="coerce").fillna(0).astype(int) > 0
        tags = df.get("enter_tag", pd.Series("", index=df.index)).astype("string").fillna("")
        keep = pd.Series(True, index=df.index)
        if self.v25_block_vwap:
            keep &= ~tags.str.contains("vwap_reclaim", case=False, regex=False)
        if self.v25_fee_floor:
            keep &= ((df["v25_atr_pct"] >= 0.0015) | (df["v25_range60_pct"] >= 0.0040)).fillna(False)
        reject = active & ~keep
        df.loc[reject, "enter_long"] = 0
        df.loc[reject, "enter_tag"] = None
        return df

    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake, min_stake, max_stake, leverage, entry_tag, side, **kwargs):
        if self.v25_stake_policy == "parent":
            return super().custom_stake_amount(pair, current_time, current_rate, proposed_stake, min_stake, max_stake, leverage, entry_tag, side, **kwargs)
        tag = str(entry_tag or "").lower()
        if "vwap_reclaim" in tag:
            factor = 0.05
        elif "momentum_continuation" in tag or "breakout_retest" in tag:
            factor = 1.00
        elif "trend_pullback" in tag:
            factor = 0.75
        else:
            factor = 0.50
        stake = float(proposed_stake) * factor
        if min_stake is not None:
            stake = max(stake, float(min_stake))
        if max_stake is not None:
            stake = min(stake, float(max_stake))
        return stake

class M4PioneerOOSV25NoVWAP(_V25Base):
    v25_block_vwap = True
class M4PioneerOOSV25FeeFloor(_V25Base):
    v25_fee_floor = True
class M4PioneerOOSV25NoVWAPFeeFloor(_V25Base):
    v25_block_vwap = True
    v25_fee_floor = True
class M4PioneerOOSV25PathStake(_V25Base):
    v25_stake_policy = "path"
class M4PioneerOOSV25NoVWAPPathStake(_V25Base):
    v25_block_vwap = True
    v25_stake_policy = "path"
'''
    for name in CANDIDATES[1:]:
        code += f'''\nclass {name}Delay1({name}):\n    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:\n        df = super().populate_entry_trend(dataframe, metadata)\n        src = pd.to_numeric(df.get("enter_long", 0), errors="coerce").fillna(0).astype(int)\n        tag = df.get("enter_tag", pd.Series(None, index=df.index))\n        df["enter_long"] = src.shift(1).fillna(0).astype(int)\n        df["enter_tag"] = tag.shift(1).where(df["enter_long"] > 0, None)\n        return df\n'''
    path = STRATDIR / "M4PioneerOOSV25.py"
    path.write_text(code, encoding="utf-8")
    return path


def main_factory() -> int:
    started = now()
    parent_path, config_path = locate_parent()
    candidate_path = write_candidate_strategy(parent_path)
    template = json.loads(config_path.read_text()) if config_path else fallback_config()
    dump(EVIDDIR / "source_freeze.json", {
        "started": started, "parent": str(parent_path), "parent_sha256": sha256(parent_path),
        "candidate_sha256": sha256(candidate_path), "config_source": str(config_path) if config_path else "fallback",
        "freqtrade_commit": FREQTRADE_COMMIT, "alpha_development_range": TRAIN_RANGE,
        "oos_range": OOS_RANGE, "oos_opened_before_freeze": False, "max_open_trades": 1,
    })

    all_requested = ORIGINAL_PAIRS + [p for p in REPLACEMENT_POOL if p not in ORIGINAL_PAIRS]
    available: list[str] = []
    for idx, pair in enumerate(all_requested, 1):
        ok = materialize_pair(pair)
        if ok:
            available.append(pair)
        print(f"DATA {idx}/{len(all_requested)} {pair} {'PASS' if ok else 'SKIP'}", flush=True)
    if len([p for p in ORIGINAL_PAIRS if p in available]) < 25:
        raise RuntimeError("Insufficient original pair data")
    dump(EVIDDIR / "available_pairs.json", {"available": available, "missing": [p for p in all_requested if p not in available]})

    # Training-only pair screen in memory-safe batches and three chronological folds.
    screen_rows: dict[str, dict[str, Any]] = {p: {"pair": p, "folds": []} for p in available}
    for fold_name, timerange in FOLDS:
        for bstart in range(0, len(available), 8):
            batch = available[bstart:bstart+8]
            label = f"pair_screen_{fold_name}_{bstart//8:02d}"
            result = backtest(template, batch, "M4PioneerValidationV14", timerange, label, max_open=len(batch), wallet=1_000_000_000, stake=10_000)
            per = pair_metrics_from_trades(result["trades"] if result else [])
            for pair in batch:
                row = dict(per.get(pair, {"pair": pair, "trades": 0, "wins": 0, "losses": 0, "profit_usdc": 0.0, "profit_factor": 0.0, "winrate_pct": 0.0}))
                row["fold"] = fold_name
                screen_rows[pair]["folds"].append(row)

    aggregate: list[dict[str, Any]] = []
    for pair, item in screen_rows.items():
        folds = item["folds"]
        trades = sum(int(f.get("trades", 0)) for f in folds)
        wins = sum(int(f.get("wins", 0)) for f in folds)
        losses = sum(int(f.get("losses", 0)) for f in folds)
        profit = sum(float(f.get("profit_usdc", 0)) for f in folds)
        wr = 100 * wins / max(trades, 1)
        pf_values = [float(f.get("profit_factor", 0)) for f in folds if int(f.get("trades", 0)) > 0]
        min_pf = min(pf_values) if pf_values else 0.0
        min_profit = min((float(f.get("profit_usdc", 0)) for f in folds), default=0.0)
        score = (20 if min_profit > 0 else 0) + min(wr, 100)/10 + min(min_pf, 10) + math.log1p(max(trades, 0))
        aggregate.append({"pair": pair, "trades": trades, "wins": wins, "losses": losses, "winrate_pct": wr, "profit_usdc": profit, "min_fold_profit_usdc": min_profit, "min_fold_pf": min_pf, "score": score, "folds": folds})
    aggregate.sort(key=lambda r: (r["score"], r["profit_usdc"], r["trades"]), reverse=True)
    with (TABLEDIR / "pair_screen.csv").open("w", newline="", encoding="utf-8") as f:
        cols = ["pair", "trades", "wins", "losses", "winrate_pct", "profit_usdc", "min_fold_profit_usdc", "min_fold_pf", "score"]
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows([{k:r[k] for k in cols} for r in aggregate])
    by_pair = {r["pair"]: r for r in aggregate}
    retained = [p for p in ORIGINAL_PAIRS if p in by_pair and by_pair[p]["winrate_pct"] >= 70.0]
    failing = [p for p in ORIGINAL_PAIRS if p not in retained]
    replacements = [r["pair"] for r in aggregate if r["pair"] not in ORIGINAL_PAIRS and r["winrate_pct"] >= 70.0 and r["trades"] >= 10 and r["profit_usdc"] > 0]
    final_pairs = retained + replacements[:max(0, 31-len(retained))]
    if len(final_pairs) < 31:
        fallback = [r["pair"] for r in aggregate if r["pair"] not in final_pairs]
        final_pairs += fallback[:31-len(final_pairs)]
    final_pairs = sorted(final_pairs[:31], key=lambda p: by_pair.get(p, {"score": -999})["score"], reverse=True)
    if any(p not in final_pairs for p in retained):
        raise RuntimeError("Retention contract violated")
    dump(EVIDDIR / "pair_selection_receipt.json", {
        "retained_wr_ge_70": retained, "removed_wr_lt_70": failing,
        "replacements": [p for p in final_pairs if p not in ORIGINAL_PAIRS],
        "final_pairs": final_pairs, "selection_data": TRAIN_RANGE,
        "oos_used": False, "retention_contract_pass": True,
    })

    # Candidate screen on development and known chronological validation.
    candidate_rows: list[dict[str, Any]] = []
    for candidate in CANDIDATES:
        dev = backtest(template, final_pairs, candidate, DEV_RANGE, f"candidate_{candidate}_dev")
        val = backtest(template, final_pairs, candidate, KNOWN_RANGE, f"candidate_{candidate}_known")
        if not dev or not val:
            continue
        score = (
            int(dev["profit_usdc"] > 0) + int(val["profit_usdc"] > 0)
            + int(dev["winrate_pct"] > 80) + int(val["winrate_pct"] > 80)
            + min(dev["profit_factor"], 10)/10 + min(val["profit_factor"], 10)/10
            + min(dev["profit_pct"], val["profit_pct"])/10
        )
        row = {"candidate": candidate, "dev": {k:v for k,v in dev.items() if k not in ["trades","results_per_pair"]}, "known": {k:v for k,v in val.items() if k not in ["trades","results_per_pair"]}, "screen_score": score}
        candidate_rows.append(row)
    candidate_rows.sort(key=lambda r: r["screen_score"], reverse=True)
    if not candidate_rows:
        raise RuntimeError("No candidate completed")
    top = candidate_rows[:2]
    dump(EVIDDIR / "candidate_screen.json", {"rows": candidate_rows, "top2": [r["candidate"] for r in top], "oos_used": False})

    # Exact known-data stress for top two, before OOS is opened.
    stress_rows: list[dict[str, Any]] = []
    for row in top:
        candidate = row["candidate"]
        main = backtest(template, final_pairs, candidate, TRAIN_RANGE, f"stress_{candidate}_main")
        fee15 = backtest(template, final_pairs, candidate, TRAIN_RANGE, f"stress_{candidate}_fee15", fee=0.0015)
        fee20 = backtest(template, final_pairs, candidate, TRAIN_RANGE, f"stress_{candidate}_fee20", fee=0.0020)
        delay_class = candidate + "Delay1" if candidate != "M4PioneerValidationV14" else None
        delay = backtest(template, final_pairs, delay_class, TRAIN_RANGE, f"stress_{candidate}_delay1") if delay_class else None
        scenarios = [x for x in [main, fee15, fee20, delay] if x]
        positive = sum(int(x["profit_usdc"] > 0 and x["profit_factor"] > 1.0) for x in scenarios)
        min_pf = min((x["profit_factor"] for x in scenarios), default=0.0)
        stress_rows.append({"candidate": candidate, "positive_scenarios": positive, "min_pf": min_pf, "scenarios": [{k:v for k,v in x.items() if k not in ["trades","results_per_pair"]} for x in scenarios]})
    stress_rows.sort(key=lambda r: (r["positive_scenarios"], r["min_pf"], next((s["profit_pct"] for s in r["scenarios"] if s["strategy"] == r["candidate"]), -999)), reverse=True)
    selected = stress_rows[0]["candidate"]
    selected_base = selected.replace("Delay1", "")
    freeze = {
        "selected": selected_base, "selected_at": now(), "selection_range": TRAIN_RANGE,
        "pairlist": final_pairs, "pairlist_sha256": hashlib.sha256("\n".join(final_pairs).encode()).hexdigest(),
        "parent_sha256": sha256(parent_path), "candidate_module_sha256": sha256(candidate_path),
        "oos_range": OOS_RANGE, "oos_opened": False, "post_oos_tuning_forbidden": True,
        "stress_rows": stress_rows,
    }
    dump(EVIDDIR / "PRE_OOS_FREEZE.json", freeze)

    # One-shot OOS: selected candidate plus frozen anchor control; no candidate switch afterwards.
    oos_selected = backtest(template, final_pairs, selected_base, OOS_RANGE, f"oos_{selected_base}")
    oos_anchor = backtest(template, final_pairs, "M4PioneerValidationV14", OOS_RANGE, "oos_anchor_control")
    full_selected = backtest(template, final_pairs, selected_base, FULL_RANGE, f"full_{selected_base}")
    if not oos_selected or not full_selected:
        raise RuntimeError("Final OOS/full run failed")
    hard = {
        "oos_profit_gt_50": oos_selected["profit_pct"] > 50.0,
        "full_trades_gt_500": full_selected["total_trades"] > 500,
        "full_wr_gt_80": full_selected["winrate_pct"] > 80.0,
        "full_pf_gt_5": full_selected["profit_factor"] > 5.0,
        "full_mdd_lt_5": full_selected["max_drawdown_pct"] < 5.0,
    }
    decision = "RESEARCH_PROMOTION_ELIGIBLE" if all(hard.values()) else "KEEP_OR_ROLLBACK_FAIL_CLOSED"
    dump(EVIDDIR / "OOS_EXECUTION_RECEIPT.json", {
        "opened_once_at": now(), "range": OOS_RANGE, "selected_frozen_before_open": selected_base,
        "selected": {k:v for k,v in oos_selected.items() if k not in ["trades","results_per_pair"]},
        "anchor_control": {k:v for k,v in (oos_anchor or {}).items() if k not in ["trades","results_per_pair"]},
        "no_post_oos_tuning": True, "decision": decision, "hard_gates": hard,
    })

    # Native post-selection correctness attempts. Failures remain blockers, not silent passes.
    final_cfg = make_config(template, final_pairs, "final_selected", max_open=1, wallet=1000, stake="unlimited")
    lookahead_csv = EVIDDIR / "lookahead_selected.csv"
    look_cmd = [sys.executable, "-m", "freqtrade", "lookahead-analysis", "-c", str(final_cfg), "--strategy-path", str(STRATDIR), "-s", selected_base, "-i", "1m", "--timerange", DEV_RANGE, "--fee", "0.001", "--minimum-trade-amount", "10", "--targeted-trade-amount", "50", "--lookahead-analysis-exportfilename", str(lookahead_csv), "--no-color"]
    look_cp = run(look_cmd, "lookahead_selected", timeout=10800, allow_fail=True)
    look_rows = []
    if lookahead_csv.exists() and lookahead_csv.stat().st_size:
        try:
            look_rows = list(csv.DictReader(lookahead_csv.open()))
        except Exception:
            look_rows = []
    look_valid = bool(look_rows) and look_cp.returncode == 0
    dump(EVIDDIR / "LOOKAHEAD_RECEIPT.json", {"exit_code": look_cp.returncode, "rows": len(look_rows), "valid_verdict": look_valid, "csv_sha256": sha256(lookahead_csv) if lookahead_csv.exists() else None})

    rec_help = run([sys.executable, "-m", "freqtrade", "recursive-analysis", "--help"], "recursive_help", allow_fail=True)
    rec_cmd = [sys.executable, "-m", "freqtrade", "recursive-analysis", "-c", str(final_cfg), "--strategy-path", str(STRATDIR), "-s", selected_base, "-i", "1m", "--timerange", DEV_RANGE, "-p", "BTC/USDC", "ETH/USDC", "SOL/USDC", "SHIB/USDC", "--startup-candle", "200", "400", "800", "1100", "1600", "--no-color"]
    rec_cp = run(rec_cmd, "recursive_selected", timeout=10800, allow_fail=True)
    dump(EVIDDIR / "RECURSIVE_RECEIPT.json", {"exit_code": rec_cp.returncode, "valid": rec_cp.returncode == 0, "scope": ["BTC/USDC","ETH/USDC","SOL/USDC","SHIB/USDC"], "startup": [200,400,800,1100,1600]})

    # Final standalone strategy and fail-closed config.
    parent_text = parent_path.read_text(encoding="utf-8")
    candidate_text = candidate_path.read_text(encoding="utf-8")
    candidate_text = re.sub(r"^from M4PioneerValidationV14 import M4PioneerValidationV14\s*$", "", candidate_text, flags=re.M)
    standalone = FINALDIR / "M4PioneerOOSV25_FINAL.py"
    standalone.write_text(parent_text + "\n\n" + candidate_text + "\n", encoding="utf-8")
    cfg_obj = json.loads(final_cfg.read_text())
    cfg_obj["strategy"] = selected_base
    cfg_obj["dry_run"] = True
    cfg_obj["initial_state"] = "stopped"
    cfg_obj.setdefault("api_server", {})["enabled"] = False
    cfg_obj.setdefault("telegram", {})["enabled"] = False
    cfg_obj["validation_contract"] = {
        "selected_on": TRAIN_RANGE, "one_shot_oos": OOS_RANGE, "post_oos_tuning": False,
        "decision": decision, "live_trading_allowed": False, "dry_run_launch_allowed": False,
        "lookahead_valid": look_valid, "recursive_valid": rec_cp.returncode == 0,
    }
    final_config = FINALDIR / "config_M4PioneerOOSV25_FINAL.json"
    dump(final_config, cfg_obj)

    summary = {
        "run_id": "FQT-V25-OOS-FACTORY-20260826", "started": started, "finished": now(),
        "selected_candidate": selected_base, "decision": decision, "hard_gates": hard,
        "pair_selection": {"retained": retained, "removed": failing, "replacements": [p for p in final_pairs if p not in ORIGINAL_PAIRS], "final_pairs": final_pairs},
        "oos": {k:v for k,v in oos_selected.items() if k not in ["trades","results_per_pair"]},
        "full": {k:v for k,v in full_selected.items() if k not in ["trades","results_per_pair"]},
        "anchor_oos": {k:v for k,v in (oos_anchor or {}).items() if k not in ["trades","results_per_pair"]},
        "lookahead": {"valid": look_valid, "rows": len(look_rows), "exit_code": look_cp.returncode},
        "recursive": {"valid": rec_cp.returncode == 0, "exit_code": rec_cp.returncode},
        "strategy_sha256": sha256(standalone), "config_sha256": sha256(final_config),
        "oos_primary_target_gt_50": hard["oos_profit_gt_50"], "no_live": True,
    }
    dump(OUT / "FINAL_SUMMARY.json", summary)

    # Compact 5x8 comparison and screen tables.
    def compact(label: str, row: dict[str, Any]) -> dict[str, Any]:
        return {"Version/Test": label, "Zeitraum": row.get("timerange", ""), "Start-Ende": f"{row.get('starting_balance',0):.2f}->{row.get('final_balance',0):.2f}", "Trades": row.get("total_trades"), "W/L": f"{row.get('wins')}/{row.get('losses')}", "WR_pct": round(row.get("winrate_pct",0),2), "Profit": f"{row.get('profit_usdc',0):+.2f}/{row.get('profit_pct',0):+.2f}%", "PF/MDD": f"{row.get('profit_factor',0):.2f}/{row.get('max_drawdown_pct',0):.2f}%"}
    comparison = [
        compact("Anchor OOS", oos_anchor or {}), compact("V25 OOS", oos_selected), compact("V25 Full", full_selected),
        compact("V25 Known", next((x for x in top if x["candidate"] == selected_base), top[0])["known"]),
        compact("V25 Dev", next((x for x in top if x["candidate"] == selected_base), top[0])["dev"]),
    ]
    with (TABLEDIR / "COMPARISON_5x8.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(comparison[0])); w.writeheader(); w.writerows(comparison)

    # Complete evidence bundle.
    bundle = OUT / "FQT_M4PioneerOOSV25_EvidencePack_20260826.zip"
    with zipfile.ZipFile(bundle, "w", allowZip64=True) as zf:
        for p in sorted(OUT.rglob("*")):
            if p.is_file() and p != bundle:
                zf.write(p, p.relative_to(OUT).as_posix(), compress_type=zipfile.ZIP_DEFLATED)
        for p in [standalone, final_config, parent_path, candidate_path]:
            zf.write(p, f"source/{p.name}", compress_type=zipfile.ZIP_DEFLATED)
    if zipfile.ZipFile(bundle).testzip() is not None:
        raise RuntimeError("Final bundle CRC failed")
    dump(OUT / "RELEASE_MANIFEST.json", {"bundle": bundle.name, "bundle_sha256": sha256(bundle), "strategy": standalone.name, "strategy_sha256": sha256(standalone), "config": final_config.name, "config_sha256": sha256(final_config), "decision": decision})
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main_factory())
