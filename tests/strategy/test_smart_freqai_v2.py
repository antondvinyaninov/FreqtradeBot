from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


ROOT = Path(__file__).parents[2]


def load_v2():
    path = ROOT / "user_data/strategies/SmartFreqaiStrategyV2.py"
    spec = spec_from_file_location("smart_freqai_strategy_v2", path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.SmartFreqaiStrategyV2


def test_v2_uses_negative_prediction_buffer_for_exit():
    strategy = load_v2()({})
    frame = {
        "do_predict": [1, 1, 1],
        "&-forward-return": [-0.0005, -0.001, -0.002],
        "volume": [1.0, 1.0, 1.0],
    }
    import pandas as pd

    result = strategy.populate_exit_trend(pd.DataFrame(frame), {})
    assert result["exit_long"].fillna(0).tolist() == [0, 1, 1]


def test_v2_preserves_dry_run_portfolio_contract():
    import json

    config = json.loads((ROOT / "user_data/config.json").read_text())
    assert config["dry_run"] is True
    assert config["max_open_trades"] == 10
    assert config["stake_amount"] == 90
