"""Offline contracts for the live RocketRide smoke checker (no provider calls)."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "planner_smoke", Path(__file__).resolve().parents[2] / "pipelines/check_planner.py"
)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


@pytest.mark.parametrize(
    "output",
    [
        {"strategies": ["bm25"]},
        {"answers": [{"text": '{"strategies":["bm25"]}'}]},
        {"result_types": {"planner": "answers"}, "planner": {"strategies": ["bm25"]}},
    ],
)
def test_plan_uses_application_decoder(output):
    assert smoke.validate_plan(output) == ["bm25"]


@pytest.mark.parametrize(
    "output",
    [
        {},
        {"strategies": []},
        {"strategies": "bm25"},
        {"strategies": ["invented"]},
        {"strategies": ["bm25", "invented"]},
        {"strategies": ["bm25", "bm25"]},
        {"strategies": [True]},
    ],
)
def test_invalid_plan_fails(output):
    with pytest.raises(ValueError):
        smoke.validate_plan(output)


def test_ack_must_be_explicit():
    smoke.validate_acknowledgement({"acknowledged": True, "operation": "execute_play"})
    for output in ({}, {"acknowledged": "true", "operation": "execute_play"}):
        with pytest.raises(ValueError):
            smoke.validate_acknowledgement(output)


def test_diagnostic_preserves_contract_but_not_raw_secret_values():
    output = {
        "token": "secret-token",
        "answers": [
            {
                "text": '```json\n{"acknowledged":true,"operation":"execute_play","secret":"hidden"}\n```'
            }
        ],
    }
    description = smoke.describe_output(output)
    rendered = json.dumps(description)
    assert "secret-token" not in rendered
    assert "hidden" not in rendered
    assert any(item.get("fenced_json") for item in description)
    assert any(item.get("acknowledged") is True for item in description)


def test_diagnostic_is_bounded():
    output = {"answers": [{"text": "not-json"} for _ in range(1000)]}
    assert len(smoke.describe_output(output)) < 60


@pytest.mark.parametrize("failure", [None, "validation", "send", "cleanup"])
def test_lifecycle_isolated_and_failure_is_nonzero(monkeypatch, capsys, failure):
    calls = []
    original_id = json.loads(smoke.PIPE.read_text(encoding="utf-8"))["project_id"]

    class Client:
        def __init__(self, **kwargs):
            assert not any(key.startswith("ROCKETRIDE_DEPLOY_") for key in kwargs["env"])

        async def connect(self, **kwargs):
            calls.append("connect")

        async def validate(self, pipeline, **kwargs):
            assert pipeline["project_id"] != original_id
            return {"errors": ["invalid"] if failure == "validation" else [], "warnings": []}

        async def use(self, **kwargs):
            assert kwargs["use_existing"] is False
            assert kwargs["ttl"] == 120
            calls.append("use")
            return {"token": "secret-task-token"}

        async def send(self, token, payload, **kwargs):
            calls.append("send")
            if failure == "send":
                raise RuntimeError("server leaked secret-task-token")
            if json.loads(payload)["operation"] == "plan":
                return {"strategies": ["bm25"]}
            return {"acknowledged": True, "operation": "execute_play"}

        async def terminate(self, token):
            calls.append("terminate")
            if failure == "cleanup":
                raise RuntimeError("server leaked secret-task-token")

        async def disconnect(self):
            calls.append("disconnect")

    monkeypatch.setitem(sys.modules, "rocketride", SimpleNamespace(RocketRideClient=Client))
    monkeypatch.setattr(
        smoke,
        "dotenv_values",
        lambda path: {
            "ROCKETRIDE_URI": "https://example.invalid",
            "ROCKETRIDE_APIKEY": "secret",
            "ROCKETRIDE_DEPLOY_APIKEY": "deployment-secret",
        },
    )
    result = asyncio.run(smoke.main())
    output = capsys.readouterr().out
    assert "secret-task-token" not in output
    assert "deployment-secret" not in output
    assert result == (0 if failure is None else 1)
    assert calls[-1] == "disconnect"
    assert ("terminate" in calls) == (failure != "validation")
    assert json.loads(smoke.PIPE.read_text(encoding="utf-8"))["project_id"] == original_id
