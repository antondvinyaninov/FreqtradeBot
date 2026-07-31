from SmartFreqaiStrategy import SmartFreqaiStrategy


class SmartFreqaiStrategyV2(SmartFreqaiStrategy):
    """Candidate with a small negative buffer before model-driven exits."""

    def populate_exit_trend(self, dataframe, metadata):
        dataframe.loc[
            (dataframe["do_predict"] == 1)
            & (dataframe["&-forward-return"] <= -0.001)
            & (dataframe["volume"] > 0),
            "exit_long",
        ] = 1
        return dataframe
