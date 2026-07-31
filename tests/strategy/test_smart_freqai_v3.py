from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).parents[2]


def load_v3():
    path = ROOT / "user_data/strategies/SmartFreqaiStrategyV3.py"
    spec = spec_from_file_location("smart_freqai_strategy_v3", path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.SmartFreqaiStrategyV3


def test_v3_populates_tradeable_trend_indicators():
    strategy = load_v3()({})
    strategy.freqai = type("Freqai", (), {"start": lambda self, frame, metadata, owner: frame})()
    close = pd.Series([100 + index * 0.1 for index in range(100)], dtype=float)
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 1.0,
        }
    )

    result = strategy.populate_indicators(frame, {})

    assert {"trend_adx", "trend_ema_spread"} <= set(result.columns)


def test_v3_enters_only_when_prediction_covers_costs_and_market_trends():
    strategy = load_v3()({})
    frame = pd.DataFrame(
        {
            "do_predict": [1, 1, 1, 1],
            "&-forward-return": [0.006, 0.006, 0.006, 0.004],
            "trend_adx": [25.0, 15.0, 25.0, 25.0],
            "trend_ema_spread": [0.002, 0.002, -0.002, 0.002],
            "volume": [1.0, 1.0, 1.0, 1.0],
        }
    )

    result = strategy.populate_entry_trend(frame, {})

    assert result["enter_long"].fillna(0).tolist() == [1, 0, 0, 0]


def test_v3_keeps_v2_exit_buffer():
    strategy = load_v3()({})
    frame = pd.DataFrame(
        {
            "do_predict": [1, 1],
            "&-forward-return": [-0.0005, -0.001],
            "volume": [1.0, 1.0],
        }
    )

    result = strategy.populate_exit_trend(frame, {})

    assert result["exit_long"].fillna(0).tolist() == [0, 1]
