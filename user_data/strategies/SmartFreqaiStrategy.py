import talib.abstract as ta
from pandas import DataFrame

from freqtrade.strategy import IStrategy


class SmartFreqaiStrategy(IStrategy):
    """FreqAI strategy restricted to dry-run trading."""

    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "5m"
    process_only_new_candles = True
    startup_candle_count = 100
    minimal_roi = {"0": 0.03}
    stoploss = -0.03
    use_exit_signal = True

    def feature_engineering_expand_all(
        self, dataframe: DataFrame, period: int, metadata: dict, **kwargs
    ) -> DataFrame:
        dataframe["%-rsi-period"] = ta.RSI(dataframe, timeperiod=period)
        dataframe["%-adx-period"] = ta.ADX(dataframe, timeperiod=period)
        dataframe["%-atr-percent-period"] = (
            ta.ATR(dataframe, timeperiod=period) / dataframe["close"]
        )
        dataframe["%-ema-spread-period"] = (
            ta.EMA(dataframe, timeperiod=period) / ta.EMA(dataframe, timeperiod=period * 2) - 1
        )
        dataframe["%-volatility-period"] = dataframe["close"].pct_change().rolling(period).std()
        dataframe["%-relative-volume-period"] = (
            dataframe["volume"] / dataframe["volume"].rolling(period).mean()
        )
        return dataframe

    def feature_engineering_expand_basic(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        dataframe["%-return"] = dataframe["close"].pct_change()
        dataframe["%-raw-volume"] = dataframe["volume"]
        return dataframe

    def feature_engineering_standard(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        dataframe["%-hour"] = dataframe["date"].dt.hour
        dataframe["%-day-of-week"] = dataframe["date"].dt.dayofweek
        return dataframe

    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        horizon = self.freqai_info["feature_parameters"]["label_period_candles"]
        dataframe["&-forward-return"] = dataframe["close"].shift(-horizon) / dataframe["close"] - 1
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return self.freqai.start(dataframe, metadata, self)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["do_predict"] == 1)
            & (dataframe["&-forward-return"] > 0.004)
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "freqai_long")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["do_predict"] == 1)
            & (dataframe["&-forward-return"] <= 0)
            & (dataframe["volume"] > 0),
            "exit_long",
        ] = 1
        return dataframe
