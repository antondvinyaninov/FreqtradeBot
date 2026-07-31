import talib.abstract as ta
from SmartFreqaiStrategyV2 import SmartFreqaiStrategyV2


class SmartFreqaiStrategyV3(SmartFreqaiStrategyV2):
    """Candidate requiring a strong prediction in a confirmed uptrend."""

    def populate_indicators(self, dataframe, metadata):
        dataframe = super().populate_indicators(dataframe, metadata)
        dataframe["trend_adx"] = ta.ADX(dataframe, timeperiod=20)
        dataframe["trend_ema_spread"] = (
            ta.EMA(dataframe, timeperiod=20) / ta.EMA(dataframe, timeperiod=40) - 1
        )
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        dataframe.loc[
            (dataframe["do_predict"] == 1)
            & (dataframe["&-forward-return"] > 0.005)
            & (dataframe["trend_adx"] >= 20)
            & (dataframe["trend_ema_spread"] > 0)
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "freqai_trend_long")
        return dataframe
