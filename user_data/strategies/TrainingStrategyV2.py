import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib

from freqtrade.strategy import IStrategy


class TrainingStrategyV2(IStrategy):
    """Research-only successor candidate to the immutable training baseline."""

    INTERFACE_VERSION = 3

    can_short = False
    timeframe = "5m"
    process_only_new_candles = True
    startup_candle_count = 500

    minimal_roi = {"0": 0.03}
    stoploss = -0.03
    use_exit_signal = True

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema_trend"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = ""
        dataframe.loc[
            (
                qtpylib.crossed_above(dataframe["ema_fast"], dataframe["ema_slow"])
                & (dataframe["adx"] > 20)
                & (dataframe["ema_slow"] > dataframe["ema_trend"])
                & (dataframe["close"] > dataframe["ema_trend"])
                & (dataframe["rsi"] >= 50)
                & (dataframe["rsi"] <= 65)
                & (dataframe["volume"] > 0)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "confirmed_uptrend_cross")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe.loc[
            (
                qtpylib.crossed_below(dataframe["ema_fast"], dataframe["ema_slow"])
                | (dataframe["close"] < dataframe["ema_slow"])
                | (dataframe["rsi"] > 72)
            )
            & (dataframe["volume"] > 0),
            "exit_long",
        ] = 1
        return dataframe
