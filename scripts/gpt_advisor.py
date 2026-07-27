#!/usr/bin/env python3
"""Read-only GPT reviewer for recent dry-run results."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import psycopg


REPORT_KEYS = {"schema_version", "status", "summary", "anomalies", "recommended_test"}


def market_snapshot(database_url: str) -> dict:
    database_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(database_url) as connection, connection.transaction():
        connection.execute("SET TRANSACTION READ ONLY")
        row = connection.execute(
            """
            SELECT
                count(*) FILTER (
                    WHERE NOT is_open AND close_date >= now() - interval '24 hours'
                ),
                count(*) FILTER (
                    WHERE NOT is_open
                      AND close_date >= now() - interval '24 hours'
                      AND close_profit_abs > 0
                ),
                coalesce(sum(close_profit_abs) FILTER (
                    WHERE NOT is_open AND close_date >= now() - interval '24 hours'
                ), 0),
                coalesce(sum(fee_open_cost + fee_close_cost) FILTER (
                    WHERE NOT is_open AND close_date >= now() - interval '24 hours'
                ), 0),
                count(*) FILTER (WHERE is_open)
            FROM trades
            """
        ).fetchone()
    closed, wins, profit, fees, open_trades = row
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "window_hours": 24,
        "closed_trades": closed,
        "wins": wins,
        "losses": closed - wins,
        "net_profit_usdt": float(profit),
        "fees_usdt": float(fees),
        "open_trades": open_trades,
        "execution_mode": "dry_run",
    }


def response_text(stream) -> str:
    chunks: list[str] = []
    for raw_line in stream:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        event = json.loads(line[6:])
        if event.get("type") == "response.output_text.delta":
            chunks.append(event.get("delta", ""))
    return "".join(chunks)


def validate_report(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != REPORT_KEYS:
        raise ValueError("GPT report does not match the required schema")
    if value["schema_version"] != 1 or value["status"] not in {"ok", "warning", "critical"}:
        raise ValueError("GPT report has invalid schema_version or status")
    if not isinstance(value["summary"], str) or not isinstance(value["recommended_test"], str):
        raise ValueError("GPT report text fields must be strings")
    if not isinstance(value["anomalies"], list) or not all(
        isinstance(item, str) for item in value["anomalies"]
    ):
        raise ValueError("GPT report anomalies must be a string list")
    return value


def ask_gpt(snapshot: dict, *, base_url: str, api_key: str, model: str) -> dict:
    if urlparse(base_url).scheme != "https":
        raise ValueError("VIBEMODE_BASE_URL must use https")
    schema = {
        "schema_version": 1,
        "status": "ok|warning|critical",
        "summary": "short factual summary in Russian",
        "anomalies": ["up to five factual anomalies"],
        "recommended_test": "one offline test, never an order or deployment",
    }
    payload = {
        "model": model,
        "instructions": (
            "You are a read-only Freqtrade analyst. Use only the supplied numeric facts. "
            "Never recommend or issue orders, configuration changes, shell, SQL, or deployment. "
            f"Return only one JSON object with exactly this shape: {json.dumps(schema)}"
        ),
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": json.dumps(snapshot, separators=(",", ":")),
                    }
                ],
            }
        ],
        "store": False,
        "stream": True,
        "max_output_tokens": 512,
    }
    request = urllib.request.Request(  # noqa: S310 - base URL is restricted to HTTPS above.
        base_url.rstrip("/") + "/responses",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "OpenAI/Python 2.24.0",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        report = validate_report(json.loads(response_text(response)))
    return {"model": model, "snapshot": snapshot, "report": report}


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as temp:
        json.dump(report, temp, ensure_ascii=False, indent=2)
        temp.write("\n")
        temp_path = Path(temp.name)
    temp_path.replace(path)


def run_once() -> None:
    result = ask_gpt(
        market_snapshot(os.environ["FREQTRADE__DB_URL"]),
        base_url=os.environ["VIBEMODE_BASE_URL"],
        api_key=os.environ["VIBEMODE_API_KEY"],
        model=os.environ.get("VIBEMODE_MODEL", "gpt-5.6-sol"),
    )
    report_path = os.environ.get("GPT_ADVISOR_REPORT", "/freqtrade/user_data/logs/gpt_advisor.json")
    write_report(Path(report_path), result)
    print("gpt_advisor=ok model=" + result["model"], flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.once:
        run_once()
        return
    interval = max(300, int(os.environ.get("GPT_ADVISOR_INTERVAL_SECONDS", "3600")))
    while True:
        try:
            run_once()
        except Exception as error:
            print(f"gpt_advisor=error type={type(error).__name__}", flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    main()
