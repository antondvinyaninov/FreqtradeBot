#!/usr/bin/env python3
"""Export PostgreSQL candles and run a reproducible baseline backtest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_ROOT = Path(os.environ.get("RESEARCH_ROOT", "/research"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--fee", type=float, default=0.001)
    parser.add_argument("--strategy", default="TrainingStrategy")
    parser.add_argument("--freqaimodel")
    parser.add_argument("--timerange")
    parser.add_argument(
        "--skip-export",
        action="store_true",
        help="Use existing Feather files in the research volume.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("/opt/research/config/research-backtest.json"),
    )
    parser.add_argument(
        "--strategy-path",
        type=Path,
        default=Path("/opt/research/strategies"),
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], *, log_path: Path, env: dict[str, str] | None = None) -> None:
    completed = subprocess.run(
        command,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log_path.write_text(completed.stdout, encoding="utf-8")
    print(completed.stdout, end="")
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {completed.returncode}: {' '.join(command)}"
        )


def inspect_data(data_dir: Path, timeframe: str) -> dict[str, Any]:
    files = sorted(data_dir.glob(f"*-{timeframe}.feather"))
    if not files:
        raise RuntimeError(f"No Feather files found in {data_dir}")

    pairs: list[dict[str, Any]] = []
    for path in files:
        frame = pd.read_feather(path)
        dates = pd.to_datetime(frame["date"], utc=True)
        if dates.duplicated().any():
            raise RuntimeError(f"Duplicate timestamps in {path.name}")
        if not dates.is_monotonic_increasing:
            raise RuntimeError(f"Unordered timestamps in {path.name}")
        gaps = dates.diff().dropna()
        max_gap = gaps.max()
        if max_gap > pd.Timedelta(minutes=5):
            raise RuntimeError(f"Gap {max_gap} in {path.name}")
        if (
            (frame[["open", "high", "low", "close"]] <= 0).any().any()
            or (frame["volume"] < 0).any()
            or (frame["high"] < frame[["open", "low", "close"]].max(axis=1)).any()
            or (frame["low"] > frame[["open", "high", "close"]].min(axis=1)).any()
        ):
            raise RuntimeError(f"Invalid OHLCV values in {path.name}")
        pairs.append(
            {
                "file": path.name,
                "rows": len(frame),
                "start": dates.iloc[0].isoformat(),
                "end": dates.iloc[-1].isoformat(),
                "max_gap_seconds": int(max_gap.total_seconds()),
                "sha256": sha256(path),
            }
        )

    return {
        "file_count": len(files),
        "total_rows": sum(pair["rows"] for pair in pairs),
        "common_start": max(pair["start"] for pair in pairs),
        "common_end": min(pair["end"] for pair in pairs),
        "pairs": pairs,
    }


def freqtrade_version() -> str:
    completed = subprocess.run(
        ["freqtrade", "--version"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    )
    return completed.stdout.strip()


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    if not args.skip_export and "FREQTRADE__DB_URL" not in os.environ:
        raise RuntimeError("FREQTRADE__DB_URL is required for the read-only export")

    root = args.root.resolve()
    data_root = root / "data"
    exchange_dir = data_root / args.exchange
    results_root = root / "results"
    logs_root = root / "logs"
    exchange_dir.mkdir(parents=True, exist_ok=True)
    results_root.mkdir(parents=True, exist_ok=True)
    logs_root.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = results_root / run_id
    run_dir.mkdir()
    manifest_path = run_dir / "manifest.json"

    strategy_file = args.strategy_path / f"{args.strategy}.py"
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "git_revision": os.environ.get("RESEARCH_GIT_REVISION", "unknown"),
        "freqtrade_version": freqtrade_version(),
        "exchange": args.exchange,
        "timeframe": args.timeframe,
        "fee": args.fee,
        "strategy": args.strategy,
        "config_sha256": sha256(args.config),
        "strategy_sha256": sha256(strategy_file),
    }
    write_manifest(manifest_path, manifest)

    try:
        manifest["stage"] = "export"
        write_manifest(manifest_path, manifest)
        if not args.skip_export:
            export_log = logs_root / f"export-{run_id}.log"
            run(
                [
                    sys.executable,
                    "/opt/research/scripts/export_market_candles.py",
                    "--exchange",
                    args.exchange,
                    "--timeframe",
                    args.timeframe,
                    "--output",
                    str(exchange_dir),
                ],
                log_path=export_log,
            )
        manifest["data"] = inspect_data(exchange_dir, args.timeframe)

        manifest["stage"] = "backtest"
        write_manifest(manifest_path, manifest)
        backtest_log = logs_root / f"backtest-{run_id}.log"
        backtest_command = [
            "freqtrade",
            "backtesting",
            "--config",
            str(args.config),
            "--strategy",
            args.strategy,
            "--strategy-path",
            str(args.strategy_path),
            "--userdir",
            str(root / "user_data"),
            "--datadir",
            str(exchange_dir),
            "--data-format-ohlcv",
            "feather",
            "--fee",
            str(args.fee),
            "--export",
            "trades",
            "--backtest-directory",
            str(run_dir),
            "--cache",
            "none",
            "--breakdown",
            "month",
            "--no-color",
        ]
        if args.freqaimodel:
            backtest_command.extend(["--freqaimodel", args.freqaimodel])
        if args.timerange:
            backtest_command.extend(["--timerange", args.timerange])
        backtest_env = os.environ.copy()
        backtest_env.pop("FREQTRADE__DB_URL", None)
        run(backtest_command, log_path=backtest_log, env=backtest_env)

        manifest["stage"] = "artifacts"
        artifacts = sorted(path for path in run_dir.iterdir() if path.name != manifest_path.name)
        manifest["artifacts"] = [
            {
                "file": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in artifacts
            if path.is_file()
        ]
        manifest["status"] = "success"
        manifest["stage"] = "complete"
    except Exception as error:
        manifest["status"] = "failed"
        manifest["error"] = str(error)
        raise
    finally:
        manifest["finished_at"] = datetime.now(UTC).isoformat()
        write_manifest(manifest_path, manifest)


if __name__ == "__main__":
    main()
