import json
import logging
import os
import time
from datetime import datetime, timezone

import ccxt
import psycopg


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("market_data_collector")


def database_url() -> str:
    value = os.environ["FREQTRADE__DB_URL"]
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def configured_pairs() -> list[str]:
    value = os.getenv(
        "COLLECTOR_PAIRS",
        '["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT"]',
    )
    return json.loads(value)


def initialize_database(connection: psycopg.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS market_candles (
            exchange_name TEXT NOT NULL,
            pair TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            open_time TIMESTAMPTZ NOT NULL,
            open NUMERIC NOT NULL,
            high NUMERIC NOT NULL,
            low NUMERIC NOT NULL,
            close NUMERIC NOT NULL,
            volume NUMERIC NOT NULL,
            collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (exchange_name, pair, timeframe, open_time)
        )
        """
    )
    connection.commit()


def latest_candle_time(
    connection: psycopg.Connection,
    exchange_name: str,
    pair: str,
    timeframe: str,
) -> datetime | None:
    result = connection.execute(
        """
        SELECT MAX(open_time)
        FROM market_candles
        WHERE exchange_name = %s AND pair = %s AND timeframe = %s
        """,
        (exchange_name, pair, timeframe),
    )
    return result.fetchone()[0]


def store_candles(
    connection: psycopg.Connection,
    exchange_name: str,
    pair: str,
    timeframe: str,
    candles: list[list[float]],
) -> int:
    records = [
        (
            exchange_name,
            pair,
            timeframe,
            datetime.fromtimestamp(candle[0] / 1000, tz=timezone.utc),
            *candle[1:6],
        )
        for candle in candles
    ]
    if not records:
        return 0
    connection.executemany(
        """
        INSERT INTO market_candles (
            exchange_name, pair, timeframe, open_time, open, high, low, close, volume
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (exchange_name, pair, timeframe, open_time)
        DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            collected_at = NOW()
        """,
        records,
    )
    connection.commit()
    return len(records)


def collect_once(
    connection: psycopg.Connection,
    exchange: ccxt.Exchange,
    pairs: list[str],
    timeframe: str,
) -> None:
    for pair in pairs:
        latest = latest_candle_time(connection, exchange.id, pair, timeframe)
        since = int(latest.timestamp() * 1000) if latest else None
        candles = exchange.fetch_ohlcv(pair, timeframe=timeframe, since=since, limit=1000)
        stored = store_candles(connection, exchange.id, pair, timeframe, candles)
        logger.info("pair=%s fetched=%s stored=%s", pair, len(candles), stored)


def main() -> None:
    timeframe = os.getenv("COLLECTOR_TIMEFRAME", "5m")
    interval = int(os.getenv("COLLECTOR_INTERVAL_SECONDS", "300"))
    exchange = ccxt.bingx({"enableRateLimit": True})
    pairs = configured_pairs()

    with psycopg.connect(database_url()) as connection:
        initialize_database(connection)
        logger.info("collector started pairs=%s timeframe=%s", pairs, timeframe)
        while True:
            try:
                collect_once(connection, exchange, pairs, timeframe)
            except (ccxt.BaseError, psycopg.Error) as error:
                connection.rollback()
                logger.exception("collection failed: %s", error)
            time.sleep(interval)


if __name__ == "__main__":
    main()
