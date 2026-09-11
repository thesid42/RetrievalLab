from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.adapters.cognee import CogneeMemoryConstructor
from app.adapters.hydra import HydraMemoryGraph
from app.config import Settings
from app.models import (
    Diagnosis,
    Document,
    FailureType,
    QualitySignals,
    QueryProfile,
    SearchResult,
    StrategyName,
    StrategyRun,
)
from app.services.state import StateRepository


def run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def signals() -> QualitySignals:
    return QualitySignals(
        exact_token_recall=0.8,
        semantic_relevance=0.8,
        evidence_coverage=0.8,
        diversity=0.8,
        metadata_match=0.8,
        freshness=0.8,
    )


def profile() -> QueryProfile:
    return QueryProfile(
        raw_query="Why does AUTH-431 happen after enabling SSO?",
        normalized_query="why does auth 431 happen after enabling sso",
        query_type="exact_identifier_troubleshooting",
        signature="exact_identifier_troubleshooting:authentication",
        domain="authentication",
        exact_identifiers=["AUTH-431"],
        terms=["auth", "431", "sso"],
    )


def winner() -> tuple[QueryProfile, Diagnosis, StrategyRun]:
    current_profile = profile()
    document = Document(
        id="doc-auth-1",
        title="Authentication troubleshooting",
        content="Enable the identity provider before retrying SSO.",
        product="identity",
        published_at=datetime(2025, 1, 1, tzinfo=UTC),
        document_type="runbook",
    )
    result = SearchResult(
        document=document,
        score=0.9,
        rank=1,
        strategy=StrategyName.HYBRID_RERANK,
        reasons=["exact identifier"],
    )
    diagnosis = Diagnosis(
        failure_type=FailureType.LEXICAL,
        confidence=0.9,
        explanation="The baseline misses an exact identifier.",
        signals=signals(),
    )
    strategy_run = StrategyRun(
        strategy=StrategyName.HYBRID_RERANK,
        results=[result],
        quality_score=0.9,
        latency_ms=1.0,
        signals=signals(),
    )
    return current_profile, diagnosis, strategy_run


def settings(tmp_path: Path, **kwargs: Any) -> Settings:
    return Settings(_env_file=None, state_path=tmp_path / "state.db", **kwargs)


def test_cognee_native_add_cognify_and_search_contract(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v1/add":
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "pipeline_run_id": "run-1",
                    "dataset_id": "dataset-1",
                    "dataset_name": "retrievallab",
                },
                request=request,
            )
        if request.url.path == "/api/v1/cognify":
            return httpx.Response(200, json={}, request=request)
        return httpx.Response(
            200,
            json=[
                {
                    "search_result": {
                        "memory_id": "pattern:expected",
                        "query_pattern": profile().signature,
                    }
                }
            ],
            request=request,
        )

    current_profile, diagnosis, strategy_run = winner()
    configured = settings(
        tmp_path,
        cognee_api_url="https://cognee.test",
        cognee_api_key="secret",
        cognee_dataset="retrievallab",
    )
    constructor = CogneeMemoryConstructor(configured, httpx.MockTransport(handler))
    memory, status = run(constructor.construct(current_profile, diagnosis, strategy_run))

    assert status.mode == "remote-constructed"
    assert status.called is True
    assert [request.url.path for request in requests] == [
        "/api/v1/add",
        "/api/v1/cognify",
        "/api/v1/search",
    ]
    assert requests[0].headers["x-api-key"] == "secret"
    assert requests[0].headers["content-type"].startswith("multipart/form-data")
    # The native add endpoint is multipart/form-data; raw_data is a canonical
    # JSON memory and must not be sent to a fabricated /memories/construct path.
    assert b"raw_data" in requests[0].content
    assert b"datasetName" in requests[0].content
    assert all(request.url.path != "/v1/memories/construct" for request in requests)
    assert memory["query_pattern"] == current_profile.signature


def test_cognee_submission_is_not_claimed_as_construction(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/add":
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "pipeline_run_id": "run-1",
                    "dataset_id": "dataset-1",
                    "dataset_name": "retrievallab",
                },
                request=request,
            )
        return httpx.Response(503, json={"detail": "processing unavailable"}, request=request)

    current_profile, diagnosis, strategy_run = winner()
    configured = settings(
        tmp_path,
        cognee_api_url="https://cognee.test",
        cognee_api_key="secret",
    )
    constructor = CogneeMemoryConstructor(configured, httpx.MockTransport(handler))
    _memory, status = run(constructor.construct(current_profile, diagnosis, strategy_run))
    assert status.mode == "remote-submitted"
    assert "queryability" in status.detail.lower()


def test_cognee_failed_add_ack_is_not_treated_as_submission(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "status": "failed",
                "pipeline_run_id": "run-1",
                "dataset_id": "dataset-1",
                "dataset_name": "retrievallab",
            },
            request=request,
        )

    current_profile, diagnosis, strategy_run = winner()
    configured = settings(
        tmp_path,
        cognee_api_url="https://cognee.test",
        cognee_api_key="secret",
    )
    constructor = CogneeMemoryConstructor(configured, httpx.MockTransport(handler))
    _memory, status = run(constructor.construct(current_profile, diagnosis, strategy_run))
    assert status.mode == "local-fallback"
    assert calls == ["/api/v1/add"]


def test_cognee_async_or_nested_failed_cognify_stays_submitted(tmp_path: Path) -> None:
    current_profile, diagnosis, strategy_run = winner()

    for response in (
        httpx.Response(202, json={"status": "queued"}),
        httpx.Response(200, json={"dataset": {"status": "failed"}}),
    ):

        def handler(
            request: httpx.Request, cognify_response: httpx.Response = response
        ) -> httpx.Response:
            if request.url.path == "/api/v1/add":
                return httpx.Response(
                    200,
                    json={
                        "status": "success",
                        "pipeline_run_id": "run-1",
                        "dataset_id": "dataset-1",
                        "dataset_name": "retrievallab",
                    },
                    request=request,
                )
            return httpx.Response(
                cognify_response.status_code,
                json=cognify_response.json(),
                request=request,
            )

        configured = settings(
            tmp_path,
            cognee_api_url="https://cognee.test",
            cognee_api_key="secret",
        )
        constructor = CogneeMemoryConstructor(configured, httpx.MockTransport(handler))
        _memory, status = run(constructor.construct(current_profile, diagnosis, strategy_run))
        assert status.mode == "remote-submitted"


def test_cognee_quality_gate_can_skip_publish(tmp_path: Path) -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500, json={"error": "must not be called"}, request=request)

    current_profile, diagnosis, strategy_run = winner()
    configured = settings(
        tmp_path,
        cognee_api_url="https://cognee.test",
        cognee_api_key="secret",
    )
    constructor = CogneeMemoryConstructor(configured, httpx.MockTransport(handler))
    memory, status = run(
        constructor.construct(
            current_profile,
            diagnosis,
            strategy_run,
            publish=False,
            corpus_version="v1",
        )
    )
    assert status.mode == "local-fallback"
    assert called is False
    assert memory["corpus_version"] == "v1"


def _memory(profile_signature: str) -> dict[str, Any]:
    return {
        "memory_id": f"pattern:{hashlib.sha256(profile_signature.encode('utf-8')).hexdigest()[:16]}",
        "query_pattern": profile_signature,
        "failure_type": FailureType.LEXICAL.value,
        "winning_strategy": StrategyName.BM25.value,
        "useful_document_ids": ["doc-auth-1"],
        "quality": 0.9,
        "corpus_version": "v1",
    }


def test_hydra_empty_recall_is_authoritative_and_uses_tenant_scope(tmp_path: Path) -> None:
    current_profile = profile()
    state = StateRepository(tmp_path / "state.db", corpus_version="v1")
    state.upsert_memory(_memory(current_profile.signature))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"chunks": []}, request=request)

    configured = settings(
        tmp_path,
        hydradb_api_url="https://hydra.test",
        hydradb_api_key="secret",
        hydradb_tenant_id="tenant-1",
        hydradb_sub_tenant_id="retrievallab",
    )
    hydra = HydraMemoryGraph(configured, state, httpx.MockTransport(handler))
    match, status = run(hydra.find_play(current_profile))

    assert match is None
    assert status.mode == "remote"
    assert json.loads(requests[0].content)["tenant_id"] == "tenant-1"
    assert json.loads(requests[0].content)["sub_tenant_id"] == "retrievallab"
    assert requests[0].url.path == "/recall/recall_preferences"


def test_hydra_write_uses_add_memory_and_reports_queued_only(tmp_path: Path) -> None:
    current_profile = profile()
    state = StateRepository(tmp_path / "state.db", corpus_version="v1")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "success": True,
                "results": [
                    {
                        "source_id": _memory(profile().signature)["memory_id"],
                        "status": "queued",
                    }
                ],
                "success_count": 1,
                "failed_count": 0,
            },
            request=request,
        )

    configured = settings(
        tmp_path,
        hydradb_api_url="https://hydra.test",
        hydradb_api_key="secret",
        hydradb_tenant_id="tenant-1",
    )
    hydra = HydraMemoryGraph(configured, state, httpx.MockTransport(handler))
    status = run(hydra.write(_memory(current_profile.signature), promoted=True))

    assert status.mode == "remote-submitted"
    assert requests[0].url.path == "/memories/add_memory"
    payload = json.loads(requests[0].content)
    assert payload["tenant_id"] == "tenant-1"
    assert payload["upsert"] is True
    item = payload["memories"][0]
    assert item["source_id"] == _memory(current_profile.signature)["memory_id"]
    assert json.loads(item["text"])["query_pattern"] == current_profile.signature
    assert state.find_memory(current_profile.signature) is not None


def test_hydra_invalid_memory_never_promotes_or_calls_remote(tmp_path: Path) -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"success": True}, request=request)

    configured = settings(
        tmp_path,
        hydradb_api_url="https://hydra.test",
        hydradb_api_key="secret",
        hydradb_tenant_id="tenant-1",
    )
    state = StateRepository(tmp_path / "state.db", corpus_version="v1")
    hydra = HydraMemoryGraph(configured, state, httpx.MockTransport(handler))
    status = run(hydra.write({"query_pattern": profile().signature}, promoted=True))
    assert status.mode == "error-fallback"
    assert called is False
    assert state.find_memory(profile().signature) is None


def test_hydra_rejects_poisoned_signature_corpus_identity_and_low_score(tmp_path: Path) -> None:
    current_profile = profile()
    state = StateRepository(tmp_path / "state.db", corpus_version="v1")
    local = _memory(current_profile.signature)
    state.upsert_memory(local)
    candidate = {
        **local,
        "successful_runs": 3,
    }
    cases = [
        {**candidate, "query_pattern": "other-signature"},
        {**candidate, "corpus_version": "v2"},
        {**candidate, "memory_id": "pattern:attacker"},
    ]
    score = {**candidate}

    for index, item in enumerate([*cases, score]):
        response_body = {
            "chunks": [
                {
                    "source_id": item["memory_id"],
                    "chunk_content": json.dumps(item),
                    "relevancy_score": 0.1 if index == 3 else 0.99,
                }
            ]
        }

        def handler(request: httpx.Request, body: dict[str, Any] = response_body) -> httpx.Response:
            return httpx.Response(200, json=body, request=request)

        configured = settings(
            tmp_path,
            hydradb_api_url="https://hydra.test",
            hydradb_api_key="secret",
            hydradb_tenant_id="tenant-1",
        )
        hydra = HydraMemoryGraph(configured, state, httpx.MockTransport(handler))
        match, status = run(hydra.find_play(current_profile))
        assert match is None
        assert status.mode == "remote"


def test_hydra_queue_ack_must_match_the_written_source_id(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "success": True,
                "results": [{"source_id": "pattern:other", "status": "queued"}],
                "success_count": 1,
                "failed_count": 0,
            },
            request=request,
        )

    configured = settings(
        tmp_path,
        hydradb_api_url="https://hydra.test",
        hydradb_api_key="secret",
        hydradb_tenant_id="tenant-1",
    )
    state = StateRepository(tmp_path / "state.db", corpus_version="v1")
    hydra = HydraMemoryGraph(configured, state, httpx.MockTransport(handler))
    status = run(hydra.write(_memory(profile().signature), promoted=True))
    assert status.mode == "local-fallback"
