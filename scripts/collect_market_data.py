import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import ccxt
import psycopg
import requests


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("market_data_collector")
FEAR_GREED_SOURCE = "alternative.me"
FEAR_GREED_URL = "https://api.alternative.me/fng/"
BYBIT_OPEN_INTEREST_URL = "https://api.bybit.com/v5/market/open-interest"


def database_url() -> str:
    value = os.environ["FREQTRADE__DB_URL"]
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def configured_pairs() -> list[str]:
    value = os.getenv(
        "COLLECTOR_PAIRS",
        (
            '["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", '
            '"BNB/USDT", "XRP/USDT", "ADA/USDT", "AVAX/USDT", '
            '"LINK/USDT", "TRX/USDT"]'
        ),
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
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS market_sentiment (
            source_name TEXT NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL,
            fear_greed_value SMALLINT NOT NULL,
            classification TEXT NOT NULL,
            collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (source_name, observed_at)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS market_funding_rates (
            exchange_name TEXT NOT NULL,
            pair TEXT NOT NULL,
            funding_time TIMESTAMPTZ NOT NULL,
            funding_rate NUMERIC NOT NULL,
            collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (exchange_name, pair, funding_time)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS market_open_interest (
            exchange_name TEXT NOT NULL,
            pair TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL,
            open_interest_amount NUMERIC NOT NULL,
            collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (exchange_name, pair, timeframe, observed_at)
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


def earliest_candle_time(
    connection: psycopg.Connection,
    exchange_name: str,
    pair: str,
    timeframe: str,
) -> datetime | None:
    result = connection.execute(
        """
        SELECT MIN(open_time)
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
    with connection.cursor() as cursor:
        cursor.executemany(
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


def backfill_pair(
    connection: psycopg.Connection,
    exchange: ccxt.Exchange,
    pair: str,
    timeframe: str,
    history_days: int,
) -> None:
    if history_days <= 0:
        return

    earliest = earliest_candle_time(connection, exchange.id, pair, timeframe)
    if earliest is None:
        candles = exchange.fetch_ohlcv(pair, timeframe=timeframe, limit=1000)
        stored = store_candles(connection, exchange.id, pair, timeframe, candles)
        logger.info("bootstrap pair=%s fetched=%s stored=%s", pair, len(candles), stored)
        earliest = earliest_candle_time(connection, exchange.id, pair, timeframe)
        if earliest is None:
            return

    target_time = datetime.now(timezone.utc) - timedelta(days=history_days)
    timeframe_milliseconds = exchange.parse_timeframe(timeframe) * 1000

    while earliest > target_time:
        earliest_milliseconds = int(earliest.timestamp() * 1000)
        since = max(
            int(target_time.timestamp() * 1000),
            earliest_milliseconds - (timeframe_milliseconds * 1000),
        )
        candles = exchange.fetch_ohlcv(pair, timeframe=timeframe, since=since, limit=1000)
        stored = store_candles(connection, exchange.id, pair, timeframe, candles)
        updated_earliest = earliest_candle_time(connection, exchange.id, pair, timeframe)
        logger.info(
            "backfill pair=%s fetched=%s stored=%s earliest=%s",
            pair,
            len(candles),
            stored,
            updated_earliest,
        )
        if not candles or updated_earliest is None or updated_earliest >= earliest:
            logger.warning("backfill stopped without older candles pair=%s", pair)
            return
        earliest = updated_earliest


def latest_sentiment_time(connection: psycopg.Connection) -> datetime | None:
    result = connection.execute(
        """
        SELECT MAX(observed_at)
        FROM market_sentiment
        WHERE source_name = %s
        """,
        (FEAR_GREED_SOURCE,),
    )
    return result.fetchone()[0]


def collect_fear_greed(connection: psycopg.Connection, history_days: int) -> None:
    limit = max(history_days, 1) if latest_sentiment_time(connection) is None else 1
    response = requests.get(FEAR_GREED_URL, params={"limit": limit, "format": "json"}, timeout=15)
    response.raise_for_status()
    observations = response.json()["data"]
    records = [
        (
            FEAR_GREED_SOURCE,
            datetime.fromtimestamp(int(observation["timestamp"]), tz=timezone.utc),
            int(observation["value"]),
            observation["value_classification"],
        )
        for observation in observations
    ]
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO market_sentiment (
                source_name, observed_at, fear_greed_value, classification
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (source_name, observed_at)
            DO UPDATE SET
                fear_greed_value = EXCLUDED.fear_greed_value,
                classification = EXCLUDED.classification,
                collected_at = NOW()
            """,
            records,
        )
    connection.commit()
    logger.info("fear_greed fetched=%s stored=%s", len(observations), len(records))


def latest_derivative_time(
    connection: psycopg.Connection,
    table_name: str,
    timestamp_column: str,
    exchange_name: str,
    pair: str,
    timeframe: str | None = None,
) -> datetime | None:
    where_clause = "exchange_name = %s AND pair = %s"
    parameters: list[str] = [exchange_name, pair]
    if timeframe is not None:
        where_clause += " AND timeframe = %s"
        parameters.append(timeframe)
    result = connection.execute(
        f"SELECT MAX({timestamp_column}) FROM {table_name} WHERE {where_clause}",
        parameters,
    )
    return result.fetchone()[0]


def earliest_derivative_time(
    connection: psycopg.Connection,
    table_name: str,
    timestamp_column: str,
    exchange_name: str,
    pair: str,
    timeframe: str | None = None,
) -> datetime | None:
    where_clause = "exchange_name = %s AND pair = %s"
    parameters: list[str] = [exchange_name, pair]
    if timeframe is not None:
        where_clause += " AND timeframe = %s"
        parameters.append(timeframe)
    result = connection.execute(
        f"SELECT MIN({timestamp_column}) FROM {table_name} WHERE {where_clause}",
        parameters,
    )
    return result.fetchone()[0]


def history_start(latest: datetime | None, history_days: int) -> int:
    if latest is not None:
        return int(latest.timestamp() * 1000) + 1
    return int((datetime.now(timezone.utc) - timedelta(days=history_days)).timestamp() * 1000)


def store_funding_rates(
    connection: psycopg.Connection,
    exchange_name: str,
    pair: str,
    funding_rates: list[dict],
) -> int:
    records = [
        (
            exchange_name,
            pair,
            datetime.fromtimestamp(rate["timestamp"] / 1000, tz=timezone.utc),
            rate["fundingRate"],
        )
        for rate in funding_rates
    ]
    if not records:
        return 0
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO market_funding_rates (
                exchange_name, pair, funding_time, funding_rate
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (exchange_name, pair, funding_time)
            DO UPDATE SET
                funding_rate = EXCLUDED.funding_rate,
                collected_at = NOW()
            """,
            records,
        )
    connection.commit()
    return len(records)


def store_open_interest(
    connection: psycopg.Connection,
    exchange_name: str,
    pair: str,
    timeframe: str,
    observations: list[dict],
) -> int:
    records = [
        (
            exchange_name,
            pair,
            timeframe,
            datetime.fromtimestamp(int(observation["timestamp"]) / 1000, tz=timezone.utc),
            observation["openInterest"],
        )
        for observation in observations
    ]
    if not records:
        return 0
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO market_open_interest (
                exchange_name, pair, timeframe, observed_at, open_interest_amount
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (exchange_name, pair, timeframe, observed_at)
            DO UPDATE SET
                open_interest_amount = EXCLUDED.open_interest_amount,
                collected_at = NOW()
            """,
            records,
        )
    connection.commit()
    return len(records)


def collect_bybit_funding(
    connection: psycopg.Connection,
    exchange: ccxt.Exchange,
    pairs: list[str],
    history_days: int,
) -> None:
    for pair in pairs:
        latest = latest_derivative_time(
            connection,
            "market_funding_rates",
            "funding_time",
            exchange.id,
            pair,
        )
        since = history_start(latest, history_days)
        while True:
            funding_rates = exchange.fetch_funding_rate_history(f"{pair}:USDT", since=since, limit=200)
            stored = store_funding_rates(connection, exchange.id, pair, funding_rates)
            logger.info("bybit funding pair=%s fetched=%s stored=%s", pair, len(funding_rates), stored)
            if len(funding_rates) < 200:
                break
            last_timestamp = funding_rates[-1]["timestamp"]
            if last_timestamp < since:
                break
            since = last_timestamp + 1


def fetch_bybit_open_interest(
    pair: str,
    timeframe: str,
    start_time: int,
    end_time: int,
) -> list[dict]:
    response = requests.get(
        BYBIT_OPEN_INTEREST_URL,
        params={
            "category": "linear",
            "symbol": pair.replace("/", ""),
            "intervalTime": timeframe,
            "startTime": start_time,
            "endTime": end_time,
            "limit": 200,
        },
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if payload["retCode"] != 0:
        raise requests.RequestException(payload["retMsg"])
    return payload["result"]["list"]


def collect_bybit_open_interest(
    connection: psycopg.Connection,
    exchange: ccxt.Exchange,
    pairs: list[str],
    timeframe: str,
    history_days: int,
) -> None:
    for pair in pairs:
        target_time = datetime.now(timezone.utc) - timedelta(days=history_days)
        target_milliseconds = int(target_time.timestamp() * 1000)
        earliest = earliest_derivative_time(
            connection,
            "market_open_interest",
            "observed_at",
            exchange.id,
            pair,
            timeframe,
        )
        if earliest is not None and earliest <= target_time:
            latest = latest_derivative_time(
                connection,
                "market_open_interest",
                "observed_at",
                exchange.id,
                pair,
                timeframe,
            )
            start_time = history_start(latest, history_days)
            observations = fetch_bybit_open_interest(
                pair,
                timeframe,
                start_time,
                int(datetime.now(timezone.utc).timestamp() * 1000),
            )
            stored = store_open_interest(connection, exchange.id, pair, timeframe, observations)
            logger.info("bybit oi pair=%s fetched=%s stored=%s", pair, len(observations), stored)
            continue

        end_time = (
            int(earliest.timestamp() * 1000) - 1
            if earliest is not None
            else int(datetime.now(timezone.utc).timestamp() * 1000)
        )
        while end_time > target_milliseconds:
            observations = fetch_bybit_open_interest(
                pair,
                timeframe,
                target_milliseconds,
                end_time,
            )
            stored = store_open_interest(connection, exchange.id, pair, timeframe, observations)
            updated_earliest = earliest_derivative_time(
                connection,
                "market_open_interest",
                "observed_at",
                exchange.id,
                pair,
                timeframe,
            )
            logger.info(
                "bybit oi backfill pair=%s fetched=%s stored=%s earliest=%s",
                pair,
                len(observations),
                stored,
                updated_earliest,
            )
            if (
                not observations
                or updated_earliest is None
                or (earliest is not None and updated_earliest >= earliest)
            ):
                return
            earliest = updated_earliest
            end_time = int(earliest.timestamp() * 1000) - 1

        latest = latest_derivative_time(
            connection,
            "market_open_interest",
            "observed_at",
            exchange.id,
            pair,
            timeframe,
        )
        if latest is None:
            continue
        observations = fetch_bybit_open_interest(
            pair,
            timeframe,
            history_start(latest, history_days),
            int(datetime.now(timezone.utc).timestamp() * 1000),
        )
        stored = store_open_interest(connection, exchange.id, pair, timeframe, observations)
        logger.info("bybit oi pair=%s fetched=%s stored=%s", pair, len(observations), stored)


def collect_once(
    connection: psycopg.Connection,
    exchange: ccxt.Exchange,
    pairs: list[str],
    timeframe: str,
    history_days: int,
) -> None:
    for pair in pairs:
        backfill_pair(connection, exchange, pair, timeframe, history_days)
        latest = latest_candle_time(connection, exchange.id, pair, timeframe)
        since = int(latest.timestamp() * 1000) if latest else None
        candles = exchange.fetch_ohlcv(pair, timeframe=timeframe, since=since, limit=1000)
        stored = store_candles(connection, exchange.id, pair, timeframe, candles)
        logger.info("pair=%s fetched=%s stored=%s", pair, len(candles), stored)


def main() -> None:
    timeframe = os.getenv("COLLECTOR_TIMEFRAME", "5m")
    interval = int(os.getenv("COLLECTOR_INTERVAL_SECONDS", "300"))
    bingx_history_days = int(os.getenv("COLLECTOR_HISTORY_DAYS", "45"))
    binance_history_days = int(os.getenv("BINANCE_HISTORY_DAYS", "180"))
    bybit_history_days = int(os.getenv("BYBIT_DERIVATIVES_HISTORY_DAYS", "180"))
    bybit_oi_timeframe = os.getenv("BYBIT_OI_TIMEFRAME", "1h")
    fear_greed_history_days = int(os.getenv("FEAR_GREED_HISTORY_DAYS", "180"))
    bingx = ccxt.bingx({"enableRateLimit": True})
    binance = ccxt.binance({"enableRateLimit": True})
    bybit = ccxt.bybit({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    pairs = configured_pairs()

    with psycopg.connect(database_url()) as connection:
        initialize_database(connection)
        logger.info(
            "collector started pairs=%s timeframe=%s bingx_history_days=%s binance_history_days=%s",
            pairs,
            timeframe,
            bingx_history_days,
            binance_history_days,
        )
        while True:
            try:
                collect_fear_greed(connection, fear_greed_history_days)
                collect_once(connection, bingx, pairs, timeframe, bingx_history_days)
                collect_once(connection, binance, pairs, timeframe, binance_history_days)
                collect_bybit_funding(connection, bybit, pairs, bybit_history_days)
                collect_bybit_open_interest(
                    connection,
                    bybit,
                    pairs,
                    bybit_oi_timeframe,
                    bybit_history_days,
                )
            except (ccxt.BaseError, psycopg.Error, requests.RequestException) as error:
                connection.rollback()
                logger.exception("collection failed: %s", error)
            time.sleep(interval)


if __name__ == "__main__":
    main()
