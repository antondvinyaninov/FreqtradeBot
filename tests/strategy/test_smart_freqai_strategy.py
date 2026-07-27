import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd


STRATEGY_PATH = Path(__file__).parents[2] / "user_data/strategies/SmartFreqaiStrategy.py"
CONFIG_PATH = Path(__file__).parents[2] / "user_data/config.json"


def load_strategy_class():
    spec = spec_from_file_location("smart_freqai_strategy", STRATEGY_PATH)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.SmartFreqaiStrategy


def make_strategy():
    return load_strategy_class()({})


def candles(rows: int = 80) -> pd.DataFrame:
    close = pd.Series([100 + index * 0.1 for index in range(rows)], dtype=float)
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=rows, freq="5min", tz="UTC"),
            "open": close,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 1000.0,
        }
    )


def test_smart_strategy_contract_and_features():
    strategy = make_strategy()

    assert strategy.timeframe == "5m"
    assert strategy.can_short is False
    assert strategy.process_only_new_candles is True
    assert strategy.startup_candle_count >= 50
    assert strategy.stoploss == -0.03

    frame = strategy.feature_engineering_expand_all(candles(), 20, {})
    assert {
        "%-rsi-period",
        "%-adx-period",
        "%-atr-percent-period",
        "%-ema-spread-period",
        "%-volatility-period",
        "%-relative-volume-period",
    } <= set(frame.columns)

    frame = strategy.feature_engineering_expand_basic(frame, {})
    assert {"%-return", "%-raw-volume"} <= set(frame.columns)

    frame = strategy.feature_engineering_standard(frame, {})
    assert {"%-hour", "%-day-of-week"} <= set(frame.columns)


def test_target_is_twelve_candle_forward_return():
    strategy = make_strategy()
    strategy.freqai_info = {"feature_parameters": {"label_period_candles": 12}}
    frame = candles()

    result = strategy.set_freqai_targets(frame.copy(), {})

    expected = frame["close"].shift(-12) / frame["close"] - 1
    pd.testing.assert_series_equal(result["&-forward-return"], expected, check_names=False)


def test_entries_and_exits_require_valid_predictions():
    strategy = make_strategy()
    frame = pd.DataFrame(
        {
            "do_predict": [1, 1, 0, 1],
            "&-forward-return": [0.005, 0.003, 0.010, 0.010],
            "volume": [1.0, 1.0, 1.0, 0.0],
        }
    )

    entries = strategy.populate_entry_trend(frame.copy(), {})
    assert entries["enter_long"].fillna(0).tolist() == [1, 0, 0, 0]
    assert entries.loc[0, "enter_tag"] == "freqai_long"

    exit_frame = pd.DataFrame(
        {
            "do_predict": [1, 1, 0],
            "&-forward-return": [-0.001, 0.001, -0.001],
            "volume": [1.0, 1.0, 1.0],
        }
    )
    exits = strategy.populate_exit_trend(exit_frame, {})
    assert exits["exit_long"].fillna(0).tolist() == [1, 0, 0]


def test_server_config_keeps_dry_run_and_enables_temporal_freqai():
    config = json.loads(CONFIG_PATH.read_text())

    assert config["dry_run"] is True
    assert config["trading_mode"] == "spot"
    assert config["max_open_trades"] == 1
    assert config["stake_amount"] == 100
    assert config["freqai"]["enabled"] is True
    assert config["freqai"]["identifier"] == "smart-freqai-v1"
    assert config["freqai"]["data_split_parameters"]["shuffle"] is False
