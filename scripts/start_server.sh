#!/bin/sh
set -eu
python /freqtrade/scripts/gpt_advisor.py &
if [ "$#" -gt 0 ]; then
    exec "$@"
else
    exec freqtrade trade --logfile /freqtrade/user_data/logs/freqtrade.log --config /freqtrade/user_data/config.json --config /freqtrade/user_data/nfi-live.json --strategy NostalgiaForInfinityX7
fi
