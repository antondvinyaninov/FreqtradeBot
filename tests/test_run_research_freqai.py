import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts/run_research_baseline.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("run_research_baseline", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_runner_accepts_freqai_model_and_timerange():
    runner = load_runner()
    argv = [
        "run_research_baseline.py",
        "--freqaimodel",
        "LightGBMRegressor",
        "--timerange",
        "20260701-20260731",
    ]
    with patch.object(sys, "argv", argv):
        args = runner.parse_args()
    assert args.freqaimodel == "LightGBMRegressor"
    assert args.timerange == "20260701-20260731"
