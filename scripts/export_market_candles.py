#!/usr/bin/env python3
"""Export audited OHLCV candles from PostgreSQL to Freqtrade Feather files."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd
import psycopg


def database_url() -> str:
    value = os.environ["FREQTRADE__DB_URL"]
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def filename_for_pair(pair: str, timeframe: str) -> str:
    return f"{pair.replace('/', '_').replace(':', '_')}-{timeframe}.feather"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(database_url()) as connection, connection.transaction():
        connection.execute("SET TRANSACTION READ ONLY")
        pairs = [
            row[0]
            for row in connection.execute(
                """
                SELECT DISTINCT pair
                FROM market_candles
                WHERE exchange_name = %s AND timeframe = %s
                ORDER BY pair
                """,
                (args.exchange, args.timeframe),
            )
        ]

        if not pairs:
            raise RuntimeError(f"No candles found for {args.exchange=} {args.timeframe=}")

        for pair in pairs:
            rows = connection.execute(
                """
                SELECT open_time, open, high, low, close, volume
                FROM market_candles
                WHERE exchange_name = %s AND timeframe = %s AND pair = %s
                ORDER BY open_time
                """,
                (args.exchange, args.timeframe, pair),
            ).fetchall()

            frame = pd.DataFrame(
                rows,
                columns=["date", "open", "high", "low", "close", "volume"],
            )
            frame["date"] = pd.to_datetime(frame["date"], utc=True)
            for column in ("open", "high", "low", "close", "volume"):
                frame[column] = frame[column].astype(float)

            if frame["date"].duplicated().any():
                raise RuntimeError(f"Duplicate timestamps found for {pair}")
            if not frame["date"].is_monotonic_increasing:
                raise RuntimeError(f"Timestamps are not ordered for {pair}")

            destination = args.output / filename_for_pair(pair, args.timeframe)
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            frame.to_feather(temporary)
            temporary.replace(destination)
            print(
                f"exported pair={pair} rows={len(frame)} "
                f"start={frame['date'].iloc[0]} end={frame['date'].iloc[-1]} "
                f"file={destination}"
            )


if __name__ == "__main__":
    main()
