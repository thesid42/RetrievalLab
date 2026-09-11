#!/usr/bin/env python3
"""Validate and smoke-test pipelines/retrievallab_planner.pipe against the connected RocketRide server."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPE = ROOT / "pipelines" / "retrievallab_planner.pipe"
SOURCE = "webhook_1"


async def main() -> int:
    try:
        from rocketride import RocketRideClient
    except ImportError:
        print("FAIL: rocketride SDK not installed. From backend/: pip install -e '.[dev,native]'", file=sys.stderr)
        return 1

    if not PIPE.is_file():
        print(f"FAIL: missing {PIPE}", file=sys.stderr)
        return 1

    pipeline = json.loads(PIPE.read_text(encoding="utf-8"))
    async with RocketRideClient() as client:
        print("connected; validating pipeline")
        result = await client.validate(pipeline, source=SOURCE)
        print("validate:", json.dumps(result, default=str)[:1000])

        started = await client.use(filepath=str(PIPE), source=SOURCE)
        token = started.get("token") if isinstance(started, dict) else None
        if not isinstance(token, str) or not token:
            print("FAIL: use() returned no token", started, file=sys.stderr)
            return 1
        print("use: token received")

        payload = {
            "operation": "plan",
            "query": "Why does AUTH-431 happen after enabling SSO?",
            "profile": {
                "raw_query": "Why does AUTH-431 happen after enabling SSO?",
                "query_type": "exact_identifier_troubleshooting",
            },
            "diagnosis": {"failure_type": "lexical_failure", "confidence": 0.8},
            "registered_tools": ["bm25", "hybrid", "hybrid_rerank"],
        }
        try:
            output = await client.send(
                token,
                json.dumps(payload, separators=(",", ":")),
                objinfo={"name": "retrievallab.json"},
                mimetype="application/json",
            )
            print("send result keys:", list(output.keys()) if isinstance(output, dict) else type(output))
            print("send result sample:", json.dumps(output, default=str)[:1500])
        finally:
            await client.terminate(token)
            print("terminate: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
