from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.adapters.rocketride import RocketRideOrchestrator, _default_client_factory
from app.adapters.rote import CLIResult, RotePlaybook
from app.models import Diagnosis, FailureType, QualitySignals, StrategyName, StrategyRun
from app.services.analyzer import diagnose
from app.services.query import understand_query
from app.services.state import StateRepository


def run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def profile():
    return understand_query("Why does AUTH-431 happen after enabling SSO?")


def diagnosis():
    current = profile()
    return Diagnosis(
        failure_type=FailureType.LEXICAL,
        confidence=0.8,
        explanation="test",
        signals=diagnose(current, []).signals,
    )


def settings(tmp_path: Path, **kwargs: Any) -> SimpleNamespace:
    values = {
        "rocketride_uri": None,
        "rocketride_api_key": None,
        "rocketride_pipeline_path": None,
        "rocketride_source_id": None,
        "request_timeout_seconds": 2.0,
        "rote_cli_path": "rote",
        "rote_play_ref": None,
        "rote_timeout_seconds": 3.0,
    }
    values.update(kwargs)
    return SimpleNamespace(**values)


class FakeRocketRideClient:
    def __init__(self, calls: list[tuple[str, Any]], output: Any | None = None):
        self.calls = calls
        self.output = output or {
            # This is the PIPELINE_RESULT shape from rocketride 1.3.0.  The
            # pipeline's dynamic text field contains the JSON planner output.
            "name": "retrievallab.json",
            "path": "",
            "objectId": "object-1",
            "result_types": {"text": "text"},
            "text": ['{"strategies":["bm25","hybrid","bm25"]}'],
        }

    async def __aenter__(self):
        self.calls.append(("enter", None))
        return self

    async def __aexit__(self, *_args):
        self.calls.append(("exit", None))

    async def use(self, **kwargs: Any):
        self.calls.append(("use", kwargs))
        return {"token": "task-token"}

    async def send(self, token: str, data: str, objinfo=None, mimetype=None):
        self.calls.append(("send", (token, json.loads(data), objinfo, mimetype)))
        return self.output

    async def terminate(self, token: str):
        self.calls.append(("terminate", token))


def test_rocketride_uses_official_sdk_boundary_and_validates_plan(tmp_path: Path) -> None:
    pipeline = tmp_path / "planner.pipe"
    pipeline.write_text("{}", encoding="utf-8")
    settings_obj = settings(
        tmp_path,
        rocketride_uri="https://api.rocketride.ai",
        rocketride_api_key="secret",
        rocketride_pipeline_path=pipeline,
        rocketride_source_id="webhook_1",
    )
    calls: list[tuple[str, Any]] = []
    client = FakeRocketRideClient(calls)
    factory_calls: list[tuple[str, str, float]] = []

    def factory(uri: str, key: str, timeout: float):
        factory_calls.append((uri, key, timeout))
        return client

    adapter = RocketRideOrchestrator(settings_obj, client_factory=factory)
    strategies, status = run(adapter.plan(profile(), diagnosis()))

    assert strategies == [StrategyName.BM25, StrategyName.HYBRID]
    assert status.mode == "native"
    assert status.called is True
    assert factory_calls == [("https://api.rocketride.ai", "secret", 2.0)]
    assert [item[0] for item in calls] == ["enter", "use", "send", "terminate", "exit"]
    assert calls[1][1]["filepath"] == str(pipeline)
    assert calls[1][1]["source"] == "webhook_1"
    assert calls[2][1][0] == "task-token"
    assert calls[2][1][1]["operation"] == "plan"


def test_rocketride_default_factory_passes_timeout_in_sdk_milliseconds(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    module = types.ModuleType("rocketride")

    class FakeSDKClient:
        def __init__(self, **kwargs: Any):
            captured.update(kwargs)

    module.RocketRideClient = FakeSDKClient
    monkeypatch.setitem(sys.modules, "rocketride", module)

    _default_client_factory("ws://localhost:5565", "key", 2.5)

    assert captured == {
        "uri": "ws://localhost:5565",
        "auth": "key",
        "request_timeout": 2500.0,
    }


def test_rocketride_profile_payload_redacts_all_query_derived_fields(tmp_path: Path) -> None:
    pipeline = tmp_path / "planner.pipe"
    pipeline.write_text("{}", encoding="utf-8")
    calls: list[tuple[str, Any]] = []
    adapter = RocketRideOrchestrator(
        settings(
            tmp_path,
            rocketride_uri="https://api.rocketride.ai",
            rocketride_api_key="secret",
            rocketride_pipeline_path=pipeline,
            rocketride_source_id="webhook_1",
        ),
        client_factory=lambda *_args: FakeRocketRideClient(calls),
    )
    secret = "sk-abcdefghijkl"
    sensitive = profile().model_copy(
        update={
            "raw_query": f"contact {secret}",
            "normalized_query": secret,
            "query_type": secret,
            "signature": secret,
            "domain": secret,
            "exact_identifiers": [secret],
            "terms": [secret],
        }
    )

    run(adapter.plan(sensitive, diagnosis()))

    payload = calls[2][1][1]["profile"]
    assert secret not in json.dumps(payload)
    assert all(value != secret for value in payload["exact_identifiers"])
    assert all(value != secret for value in payload["terms"])


def test_rocketride_missing_api_key_stays_local_even_with_pipeline(tmp_path: Path) -> None:
    pipeline = tmp_path / "planner.pipe"
    pipeline.write_text("{}", encoding="utf-8")
    factory_called = False

    def factory(*_args):
        nonlocal factory_called
        factory_called = True
        raise AssertionError("native factory must not run without an API key")

    adapter = RocketRideOrchestrator(
        settings(
            tmp_path,
            rocketride_uri="https://api.rocketride.ai",
            rocketride_api_key=None,
            rocketride_pipeline_path=pipeline,
            rocketride_source_id="webhook_1",
        ),
        client_factory=factory,
    )

    _strategies, status = run(adapter.plan(profile(), diagnosis()))

    assert status.mode == "local-fallback"
    assert status.called is False
    assert factory_called is False


def test_rocketride_timeout_is_reported_as_native_failure(tmp_path: Path) -> None:
    pipeline = tmp_path / "planner.pipe"
    pipeline.write_text("{}", encoding="utf-8")
    calls: list[tuple[str, Any]] = []

    class SlowClient(FakeRocketRideClient):
        async def send(self, token: str, data: str, objinfo=None, mimetype=None):
            await asyncio.sleep(0.05)
            return await super().send(token, data, objinfo, mimetype)

    adapter = RocketRideOrchestrator(
        settings(
            tmp_path,
            rocketride_uri="https://api.rocketride.ai",
            rocketride_api_key="secret",
            rocketride_pipeline_path=pipeline,
            rocketride_source_id="webhook_1",
            request_timeout_seconds=0.01,
        ),
        client_factory=lambda *_args: SlowClient(calls),
    )

    _strategies, status = run(adapter.plan(profile(), diagnosis()))

    assert status.mode == "local-fallback"
    assert status.called is True
    assert "TimeoutError" in status.detail


def test_rocketride_invalid_strategy_text_uses_local_plan(tmp_path: Path) -> None:
    pipeline = tmp_path / "planner.pipe"
    pipeline.write_text("{}", encoding="utf-8")
    output = {
        "name": "retrievallab.json",
        "path": "",
        "objectId": "object-2",
        "result_types": {"text": "text"},
        "text": ['{"strategies":["unknown", {"name":"bm25"}]}'],
    }
    adapter = RocketRideOrchestrator(
        settings(
            tmp_path,
            rocketride_uri="https://api.rocketride.ai",
            rocketride_api_key="secret",
            rocketride_pipeline_path=pipeline,
            rocketride_source_id="webhook_1",
        ),
        client_factory=lambda *_args: FakeRocketRideClient([], output=output),
    )

    strategies, status = run(adapter.plan(profile(), diagnosis()))

    assert strategies == [StrategyName.BM25, StrategyName.HYBRID, StrategyName.HYBRID_RERANK]
    assert status.mode == "native+local-fallback"


def test_rocketride_dispatch_does_not_claim_remote_retrieval_completion(tmp_path: Path) -> None:
    pipeline = tmp_path / "executor.pipe"
    pipeline.write_text("{}", encoding="utf-8")
    client = FakeRocketRideClient([])
    adapter = RocketRideOrchestrator(
        settings(
            tmp_path,
            rocketride_uri="ws://localhost:5565",
            rocketride_api_key="local-test-key",
            rocketride_pipeline_path=pipeline,
            rocketride_source_id="webhook_1",
        ),
        client_factory=lambda *_args: client,
    )
    current = profile()
    play = {
        "query_pattern": current.signature,
        "strategy": StrategyName.BM25,
        "version": 1,
        "steps": ["validated-step"],
    }

    status = run(adapter.execute_play(current, play))

    assert status.mode == "native+local-execution"
    assert "local hotdata execution remains authoritative" in status.detail
    assert "remote tool-step completion was not inferred" in status.detail


def test_rocketride_without_pipeline_is_local_and_does_not_import_sdk(tmp_path: Path) -> None:
    adapter = RocketRideOrchestrator(settings(tmp_path))
    strategies, status = run(adapter.plan(profile(), diagnosis()))

    assert strategies == [StrategyName.BM25, StrategyName.HYBRID, StrategyName.HYBRID_RERANK]
    assert status.mode == "local-fallback"
    assert status.called is False


def test_rote_uses_documented_play_run_argv_and_local_mirror(tmp_path: Path) -> None:
    state = StateRepository(tmp_path / "state.db")
    current = profile()
    state.capture_play(current.signature, StrategyName.BM25, ["local-step"])
    calls: list[tuple[list[str], float]] = []

    async def runner(argv, timeout):
        calls.append((list(argv), timeout))
        return CLIResult(0, '{"result":{"ok":true}}', "")

    rote = RotePlaybook(
        settings(tmp_path, rote_play_ref="https://play.modiqo.ai/acme/support@1.0.0"),
        state,
        process_runner=runner,
    )
    play, status = run(rote.recall(current.signature))

    assert play is not None
    assert status.mode == "local-fallback"
    assert status.called is False
    assert calls == []

    replay_status = run(
        rote.replay(
            parameters={
                "query": "Why does AUTH-431 happen after enabling SSO?",
                "query_pattern": current.signature,
                "strategy": StrategyName.BM25.value,
            }
        )
    )

    assert replay_status.mode == "native"
    assert replay_status.called is True
    assert calls == [
        (
            [
                "rote",
                "play",
                "run",
                "https://play.modiqo.ai/acme/support@1.0.0",
                "query=Why does AUTH-431 happen after enabling SSO?",
                f"query_pattern={current.signature}",
                "strategy=bm25",
                "--output=json",
                "--yes",
            ],
            3.0,
        )
    ]


def test_rote_capture_is_explicitly_local_only(tmp_path: Path) -> None:
    state = StateRepository(tmp_path / "state.db")
    rote = RotePlaybook(settings(tmp_path, rote_play_ref=None), state)
    winner = StrategyRun(
        strategy=StrategyName.HYBRID,
        results=[],
        quality_score=0.8,
        latency_ms=2,
        signals=QualitySignals(
            exact_token_recall=0.8,
            semantic_relevance=0.8,
            evidence_coverage=0.8,
            diversity=0.8,
            metadata_match=0.8,
            freshness=0.8,
        ),
    )

    status = run(rote.capture("semantic_question:authentication", winner))

    assert status.mode == "local"
    assert status.called is False
    assert "native capture" in status.detail
    assert state.get_play("semantic_question:authentication")["strategy"] is StrategyName.HYBRID


def test_rote_failed_native_replay_is_not_presented_as_success(tmp_path: Path) -> None:
    state = StateRepository(tmp_path / "state.db")
    current = profile()
    state.capture_play(current.signature, StrategyName.BM25, ["local-step"])

    async def runner(_argv, _timeout):
        return CLIResult(2, "", "failed")

    rote = RotePlaybook(
        settings(tmp_path, rote_play_ref="acme/support@1.0.0"),
        state,
        process_runner=runner,
    )
    play, status = run(rote.recall(current.signature))

    assert play is not None
    assert status.mode == "local-fallback"
    assert status.called is False

    replay_status = run(rote.replay())

    assert replay_status.mode == "local-fallback"
    assert replay_status.called is True
    assert "failed with exit code 2" in replay_status.detail


def test_rote_exit_zero_without_json_is_not_semantic_success(tmp_path: Path) -> None:
    state = StateRepository(tmp_path / "state.db")

    async def runner(_argv, _timeout):
        return CLIResult(0, "human report only", "")

    rote = RotePlaybook(
        settings(tmp_path, rote_play_ref="acme/support@1.0.0"),
        state,
        process_runner=runner,
    )

    status = run(rote.replay())

    assert status.mode == "native-command-completed"
    assert "no semantic success" in status.detail
