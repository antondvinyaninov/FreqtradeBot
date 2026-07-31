from SmartFreqaiStrategyV2 import SmartFreqaiStrategyV2


class SmartFreqaiStrategyV3(SmartFreqaiStrategyV2):
    """Candidate requiring a strong prediction in a confirmed uptrend."""

    def populate_entry_trend(self, dataframe, metadata):
        dataframe.loc[
            (dataframe["do_predict"] == 1)
            & (dataframe["&-forward-return"] > 0.005)
            & (dataframe["%-adx-period_20"] >= 20)
            & (dataframe["%-ema-spread-period_20"] > 0)
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "freqai_trend_long")
        return dataframe
