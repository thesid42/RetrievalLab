#!/usr/bin/env python3
"""Validate and smoke-test pipelines/retrievallab_planner.pipe against the connected RocketRide server."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback
from pathlib import Path
from uuid import uuid4

from app.adapters.rocketride import _mapping_candidates, _remote_strategies
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
PIPE = ROOT / "pipelines" / "retrievallab_planner.pipe"
SOURCE = "webhook_1"
TOOLS = ["bm25", "hybrid", "hybrid_rerank"]


def validate_plan(output: object) -> list[str]:
    """Require the exact planner contract and the application's real decoder."""
    for candidate in _mapping_candidates(output):
        values = candidate.get("strategies")
        if (
            isinstance(values, list)
            and 0 < len(values) <= 5
            and all(isinstance(value, str) and value in TOOLS for value in values)
            and len(set(values)) == len(values)
        ):
            decoded = _remote_strategies(output, set(TOOLS))
            if decoded and [item.value for item in decoded] == values:
                return values
    raise ValueError("Pipeline did not return a valid registered-tool plan")


def validate_acknowledgement(output: object) -> None:
    if not any(
        candidate.get("acknowledged") is True
        and candidate.get("operation") == "execute_play"
        for candidate in _mapping_candidates(output)
    ):
        raise ValueError("Pipeline did not acknowledge execute_play")


def describe_output(output: object) -> list[dict[str, object]]:
    """Bounded diagnostic shape; never print raw answers or secret field values."""
    observations: list[dict[str, object]] = []

    def visit(value: object, path: str, depth: int) -> None:
        if depth > 8 or len(observations) >= 60:
            return
        entry: dict[str, object] = {"path": path, "type": type(value).__name__}
        observations.append(entry)
        if isinstance(value, dict):
            if "acknowledged" in value:
                entry["acknowledged"] = (
                    value["acknowledged"]
                    if isinstance(value["acknowledged"], bool)
                    else "not-a-boolean"
                )
            if "operation" in value:
                entry["operation"] = (
                    value["operation"]
                    if value["operation"] in ("plan", "execute_play")
                    else "unrecognized"
                )
            if isinstance(value.get("strategies"), list):
                entry["strategies"] = [
                    item if isinstance(item, str) and item in TOOLS else "unrecognized"
                    for item in value["strategies"][:5]
                ]
            for key, item in list(value.items())[:12]:
                if not isinstance(key, str) or any(
                    word in key.lower()
                    for word in ("token", "secret", "auth", "key", "credential")
                ):
                    continue
                visit(item, f"{path}.{key[:48]}", depth + 1)
        elif isinstance(value, list):
            entry["length"] = len(value)
            for index, item in enumerate(value[:3]):
                visit(item, f"{path}[{index}]", depth + 1)
        elif isinstance(value, str):
            entry["length"] = len(value)
            if len(value) > 100_000:
                return
            candidate = value.strip()
            if candidate.startswith("```") and candidate.endswith("```"):
                entry["fenced_json"] = True
                candidate = candidate.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            try:
                decoded = json.loads(candidate)
            except (ValueError, TypeError):
                return
            visit(decoded, f"{path}<json>", depth + 1)

    visit(output, "$", 0)
    return observations


def failure_hint(error: Exception) -> str:
    """Classify failures without logging server messages, tokens, or credentials."""
    message = str(error).lower()
    if "authentication" in type(error).__name__.lower() or "unauthorized" in message:
        return (
            "Reconnect RocketRide in the editor to refresh its development credentials."
        )
    if any(word in message for word in ("openai", "api key", "apikey", "api_key")):
        return (
            "Check ROCKETRIDE_OPENAI_KEY in the project or RocketRide server secrets."
        )
    if isinstance(error, TimeoutError):
        return "RocketRide exceeded the bounded test timeout."
    return (
        "Inspect the matching task in the RocketRide editor; raw errors are withheld."
    )


def stage(report: dict[str, object], name: str) -> None:
    report["stage"] = name
    print(f"planner smoke: {name}", file=sys.stderr, flush=True)


def error_diagnostic(error: Exception) -> dict[str, object]:
    """Local stack locations only: no exception text, locals, or credential values."""
    return {
        "type": type(error).__name__,
        "frames": [
            {
                "file": Path(frame.filename).name,
                "function": frame.name,
                "line": frame.lineno,
            }
            for frame in traceback.extract_tb(error.__traceback__)[-5:]
        ],
        "attribute": error.name if isinstance(error, AttributeError) else None,
    }


async def main(operations: tuple[str, ...] = ("plan", "execute_play")) -> int:
    try:
        from rocketride import RocketRideClient
    except ImportError:
        print(
            "FAIL: rocketride SDK not installed. From backend/: pip install -e '.[dev,native]'",
            file=sys.stderr,
        )
        return 1

    if not PIPE.is_file():
        print(f"FAIL: missing {PIPE}", file=sys.stderr)
        return 1

    # Resolve the project .env even when invoked from a Rote workspace. Never
    # forward deployment credentials or unrelated environment secrets to use().
    env = {
        key: value
        for key, value in {**dotenv_values(ROOT / ".env"), **os.environ}.items()
        if key.startswith("ROCKETRIDE_")
        and not key.startswith("ROCKETRIDE_DEPLOY_")
        and value is not None
    }
    report: dict[str, object] = {"status": "failed", "stage": "configuration"}
    token = None
    client = None
    try:
        if not env.get("ROCKETRIDE_URI") or not env.get("ROCKETRIDE_APIKEY"):
            raise ValueError("Development connection settings are missing")
        pipeline = json.loads(PIPE.read_text(encoding="utf-8"))
        # Isolate this smoke task from the pipeline open in the editor.
        pipeline["project_id"] = str(uuid4())
        client = RocketRideClient(env=env, request_timeout=60_000)
        stage(report, "connect")
        await asyncio.wait_for(client.connect(timeout=20_000), timeout=20)
        stage(report, "validate")
        result = await asyncio.wait_for(
            client.validate(pipeline, source=SOURCE), timeout=20
        )
        if not isinstance(result, dict) or result.get("errors"):
            raise ValueError("Server rejected pipeline validation")
        report["validation"] = "passed"
        report["warning_count"] = len(result.get("warnings", []))
        stage(report, "start")
        started = await asyncio.wait_for(
            client.use(
                pipeline=pipeline,
                source=SOURCE,
                use_existing=False,
                ttl=120,
                name="retrievallab-planner-smoke",
            ),
            timeout=60,
        )
        token = started.get("token") if isinstance(started, dict) else None
        if not isinstance(token, str) or not token:
            token = None
            raise ValueError("use() returned no token")
        payload = {
            "operation": "plan",
            "query": "Why does AUTH-431 happen after enabling SSO?",
            "profile": {
                "raw_query": "Why does AUTH-431 happen after enabling SSO?",
                "query_type": "exact_identifier_troubleshooting",
            },
            "diagnosis": {"failure_type": "lexical_failure", "confidence": 0.8},
            "registered_tools": TOOLS,
        }
        for operation in operations:
            stage(report, operation)
            payload["operation"] = operation
            if operation == "execute_play":
                payload["play"] = {
                    "strategy": "bm25",
                    "version": 1,
                    "steps": ["retrieve"],
                }
            output = await asyncio.wait_for(
                client.send(
                    token,
                    json.dumps(payload, separators=(",", ":")),
                    objinfo={"name": "retrievallab.json"},
                    mimetype="application/json",
                ),
                timeout=60,
            )
            report[f"{operation}_response_shape"] = describe_output(output)
            if operation == "plan":
                report["strategies"] = validate_plan(output)
            else:
                validate_acknowledgement(output)
                report["execute_play"] = (
                    "acknowledged (not proof of retrieval execution)"
                )
        report.update(status="passed", stage="complete")
    except Exception as error:  # noqa: BLE001 - CLI boundary must not leak SDK secrets.
        report.update(
            error_type=type(error).__name__,
            hint=failure_hint(error),
            error_diagnostic=error_diagnostic(error),
        )
    finally:
        if token is not None and client is not None:
            print("planner smoke: cleanup", file=sys.stderr, flush=True)
            try:
                await asyncio.wait_for(client.terminate(token), timeout=10)
                report["cleanup"] = "terminated"
            except Exception as error:  # noqa: BLE001 - report cleanup failure without raw errors.
                report.update(status="failed", cleanup=error_diagnostic(error))
        if client is not None:
            print("planner smoke: disconnect", file=sys.stderr, flush=True)
            try:
                await asyncio.wait_for(client.disconnect(), timeout=10)
            except Exception as error:  # noqa: BLE001 - preserve failure and attempt disconnect.
                report.update(status="failed", disconnect=type(error).__name__)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    # WSL/Rote may launch Windows Python with a Linux UNC working directory.
    # Keep SDK imports and relative runtime lookups on the native project drive.
    os.chdir(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--operation", choices=("plan", "execute_play", "both"), default="both"
    )
    options = parser.parse_args()
    operations = (
        ("plan", "execute_play")
        if options.operation == "both"
        else (options.operation,)
    )
    raise SystemExit(asyncio.run(main(operations)))
