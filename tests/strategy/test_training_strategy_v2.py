from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


STRATEGY_PATH = Path(__file__).parents[2] / "user_data" / "strategies" / "TrainingStrategyV2.py"


def load_strategy_class():
    if not STRATEGY_PATH.exists():
        pytest.fail("TrainingStrategyV2 has not been implemented")
    spec = spec_from_file_location("training_strategy_v2", STRATEGY_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.TrainingStrategyV2


def test_strategy_v2_is_a_separate_loadable_strategy() -> None:
    strategy_class = load_strategy_class()

    assert strategy_class.__name__ == "TrainingStrategyV2"
    assert strategy_class.timeframe == "5m"
    assert strategy_class.can_short is False


def test_strategy_v2_populates_trend_and_strength_indicators() -> None:
    strategy_class = load_strategy_class()
    strategy = strategy_class({})
    rows = 600
    close = 100 + np.linspace(0, 20, rows) + np.sin(np.arange(rows) / 5)
    dataframe = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=rows, freq="5min", tz="UTC"),
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(rows, 1000.0),
        }
    )

    result = strategy.populate_indicators(dataframe, {"pair": "BTC/USDT"})

    assert strategy.startup_candle_count >= 500
    assert {"ema_fast", "ema_slow", "ema_trend", "rsi", "adx"} <= set(result.columns)
    assert result[["ema_fast", "ema_slow", "ema_trend", "rsi", "adx"]].iloc[-1].notna().all()


def test_strategy_v2_enters_on_a_confirmed_uptrend_crossover() -> None:
    strategy = load_strategy_class()({})
    dataframe = pd.DataFrame(
        {
            "ema_fast": [99.0, 101.0],
            "ema_slow": [100.0, 100.0],
            "ema_trend": [90.0, 90.0],
            "close": [104.0, 105.0],
            "rsi": [54.0, 56.0],
            "adx": [24.0, 25.0],
            "volume": [1000.0, 1000.0],
        }
    )

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT"})

    enter_long = result.get("enter_long", pd.Series(0, index=result.index))
    assert enter_long.iloc[-1] == 1
    assert result.loc[result.index[-1], "enter_tag"] == "confirmed_uptrend_cross"


def test_strategy_v2_rejects_a_weak_trend_crossover() -> None:
    strategy = load_strategy_class()({})
    dataframe = pd.DataFrame(
        {
            "ema_fast": [99.0, 101.0],
            "ema_slow": [100.0, 100.0],
            "ema_trend": [90.0, 90.0],
            "close": [104.0, 105.0],
            "rsi": [54.0, 56.0],
            "adx": [10.0, 10.0],
            "volume": [1000.0, 1000.0],
        }
    )

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT"})

    assert np.issubdtype(result["enter_long"].dtype, np.number)
    assert result["enter_long"].iloc[-1] == 0


def test_strategy_v2_rejects_crossover_below_the_long_term_trend() -> None:
    strategy = load_strategy_class()({})
    dataframe = pd.DataFrame(
        {
            "ema_fast": [99.0, 101.0],
            "ema_slow": [100.0, 100.0],
            "ema_trend": [110.0, 110.0],
            "close": [114.0, 115.0],
            "rsi": [54.0, 56.0],
            "adx": [24.0, 25.0],
            "volume": [1000.0, 1000.0],
        }
    )

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT"})

    assert result["enter_long"].iloc[-1] == 0


def test_strategy_v2_rejects_crossover_when_price_is_below_trend() -> None:
    strategy = load_strategy_class()({})
    dataframe = pd.DataFrame(
        {
            "ema_fast": [119.0, 121.0],
            "ema_slow": [120.0, 120.0],
            "ema_trend": [110.0, 110.0],
            "close": [109.0, 109.0],
            "rsi": [54.0, 56.0],
            "adx": [24.0, 25.0],
            "volume": [1000.0, 1000.0],
        }
    )

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT"})

    assert result["enter_long"].iloc[-1] == 0


def test_strategy_v2_rejects_an_overheated_crossover() -> None:
    strategy = load_strategy_class()({})
    dataframe = pd.DataFrame(
        {
            "ema_fast": [99.0, 101.0],
            "ema_slow": [100.0, 100.0],
            "ema_trend": [90.0, 90.0],
            "close": [104.0, 105.0],
            "rsi": [68.0, 70.0],
            "adx": [24.0, 25.0],
            "volume": [1000.0, 1000.0],
        }
    )

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT"})

    assert result["enter_long"].iloc[-1] == 0


def test_strategy_v2_rejects_crossover_without_positive_momentum() -> None:
    strategy = load_strategy_class()({})
    dataframe = pd.DataFrame(
        {
            "ema_fast": [99.0, 101.0],
            "ema_slow": [100.0, 100.0],
            "ema_trend": [90.0, 90.0],
            "close": [104.0, 105.0],
            "rsi": [46.0, 48.0],
            "adx": [24.0, 25.0],
            "volume": [1000.0, 1000.0],
        }
    )

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT"})

    assert result["enter_long"].iloc[-1] == 0


def test_strategy_v2_rejects_crossover_without_volume() -> None:
    strategy = load_strategy_class()({})
    dataframe = pd.DataFrame(
        {
            "ema_fast": [99.0, 101.0],
            "ema_slow": [100.0, 100.0],
            "ema_trend": [90.0, 90.0],
            "close": [104.0, 105.0],
            "rsi": [54.0, 56.0],
            "adx": [24.0, 25.0],
            "volume": [0.0, 0.0],
        }
    )

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT"})

    assert result["enter_long"].iloc[-1] == 0


def test_strategy_v2_exits_on_a_bearish_crossover() -> None:
    strategy = load_strategy_class()({})
    dataframe = pd.DataFrame(
        {
            "ema_fast": [101.0, 99.0],
            "ema_slow": [100.0, 100.0],
            "close": [101.0, 99.0],
            "rsi": [60.0, 55.0],
            "volume": [1000.0, 1000.0],
        }
    )

    result = strategy.populate_exit_trend(dataframe, {"pair": "BTC/USDT"})

    exit_long = result.get("exit_long", pd.Series(0, index=result.index))
    assert exit_long.iloc[-1] == 1


def test_strategy_v2_exits_when_price_loses_the_slow_average() -> None:
    strategy = load_strategy_class()({})
    dataframe = pd.DataFrame(
        {
            "ema_fast": [102.0, 102.0],
            "ema_slow": [100.0, 100.0],
            "close": [101.0, 99.0],
            "rsi": [60.0, 55.0],
            "volume": [1000.0, 1000.0],
        }
    )

    result = strategy.populate_exit_trend(dataframe, {"pair": "BTC/USDT"})

    assert result["exit_long"].iloc[-1] == 1


def test_strategy_v2_exits_when_momentum_is_overheated() -> None:
    strategy = load_strategy_class()({})
    dataframe = pd.DataFrame(
        {
            "ema_fast": [102.0, 103.0],
            "ema_slow": [100.0, 100.0],
            "close": [103.0, 104.0],
            "rsi": [70.0, 73.0],
            "volume": [1000.0, 1000.0],
        }
    )

    result = strategy.populate_exit_trend(dataframe, {"pair": "BTC/USDT"})

    assert result["exit_long"].iloc[-1] == 1


def test_strategy_v2_keeps_position_while_trend_remains_healthy() -> None:
    strategy = load_strategy_class()({})
    dataframe = pd.DataFrame(
        {
            "ema_fast": [101.0, 102.0],
            "ema_slow": [100.0, 100.0],
            "close": [103.0, 103.0],
            "rsi": [60.0, 72.0],
            "volume": [1000.0, 1000.0],
        }
    )

    result = strategy.populate_exit_trend(dataframe, {"pair": "BTC/USDT"})

    assert result["exit_long"].iloc[-1] == 0
