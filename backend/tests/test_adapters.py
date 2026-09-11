from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.adapters.hotdata import HotdataQueryEngine
from app.adapters.sponsors import (
    CogneeMemoryConstructor,
    HydraMemoryGraph,
    RemoteBridge,
    RocketRideOrchestrator,
    RotePlaybook,
)
from app.config import Settings
from app.models import Diagnosis, FailureType, StrategyName, StrategyRun
from app.services.analyzer import diagnose
from app.services.query import understand_query
from app.services.retrieval import Corpus
from app.services.state import StateRepository


def run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def stub_transport(response_body: Any, *, status_code: int = 200, empty: bool = False) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if empty:
            return httpx.Response(status_code, content=b"", request=request)
        return httpx.Response(status_code, json=response_body, request=request)

    return httpx.MockTransport(handler)


def routing_transport(responses: dict[str, Any]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = responses.get(request.url.path, {})
        return httpx.Response(200, json=body, request=request)

    return httpx.MockTransport(handler)


def bridge(transport: httpx.AsyncBaseTransport) -> RemoteBridge:
    return RemoteBridge("https://bridge.test", None, 1, transport=transport)


def profile():
    return understand_query("Why does AUTH-431 happen after enabling SSO?")


def settings(tmp_path: Path, **kwargs: Any) -> Settings:
    return Settings(_env_file=None, state_path=tmp_path / "state.db", **kwargs)


def winner(tmp_path: Path) -> tuple[Corpus, StrategyRun, Diagnosis]:
    configured = settings(tmp_path)
    corpus = Corpus(configured.corpus_path)
    current_profile = profile()
    results = corpus.search(current_profile, StrategyName.HYBRID_RERANK, 3)
    signals = diagnose(current_profile, results)
    strategy_run = StrategyRun(
        strategy=StrategyName.HYBRID_RERANK,
        results=results,
        quality_score=0.88,
        latency_ms=1.0,
        signals=signals.signals,
    )
    return corpus, strategy_run, signals


def test_remote_bridge_rejects_scalar_array_and_empty_json() -> None:
    for body in (7, ["not-an-object"], None):
        response = run(RemoteBridge("https://bridge.test", None, 1, transport=stub_transport(body)).post("/v1/test", {}))
        assert response.called is False
        assert response.attempted is True
        assert response.data is None

    empty_response = run(
        RemoteBridge(
            "https://bridge.test", None, 1, transport=stub_transport({}, empty=True)
        ).post("/v1/test", {})
    )
    assert empty_response.called is False
    assert empty_response.attempted is True


def test_hotdata_accepts_explicit_empty_results(tmp_path: Path) -> None:
    configured = settings(tmp_path)
    corpus = Corpus(configured.corpus_path)
    engine = HotdataQueryEngine(configured, corpus)
    engine.remote = bridge(stub_transport({"results": []}))

    strategy_run, status = run(engine.execute(profile(), StrategyName.BM25, 3))

    assert strategy_run.results == []
    assert status.mode == "remote+normalized-local"
    assert status.called is True


def test_hotdata_normalizes_rank_and_rejects_bad_score_or_timezone(tmp_path: Path) -> None:
    configured = settings(tmp_path)
    corpus = Corpus(configured.corpus_path)
    documents = corpus.documents[:2]
    remote_results = [
        {
            "document": documents[0].model_dump(mode="json"),
            "score": 0.25,
            "rank": 900,
            "strategy": "dense",
            "reasons": [],
        },
        {
            "document": documents[1].model_dump(mode="json"),
            "score": 0.95,
            "rank": 900,
            "strategy": "dense",
            "reasons": [],
        },
    ]
    engine = HotdataQueryEngine(configured, corpus)
    engine.remote = bridge(stub_transport({"results": remote_results}))
    strategy_run, status = run(engine.execute(profile(), StrategyName.BM25, 2))
    assert status.mode == "remote+normalized-local"
    assert [item.rank for item in strategy_run.results] == [1, 2]
    assert strategy_run.results[0].score == pytest.approx(0.95)
    assert all(item.strategy is StrategyName.BM25 for item in strategy_run.results)

    bad_score = {**remote_results[0], "score": float("nan")}
    engine.remote = bridge(stub_transport({"results": [bad_score]}))
    _, bad_score_status = run(engine.execute(profile(), StrategyName.BM25, 2))
    assert bad_score_status.mode == "local-fallback"

    naive_document = documents[0].model_copy(
        update={"published_at": datetime(2025, 1, 1)}  # noqa: DTZ001 - intentionally naive
    )
    naive_result = {**remote_results[0], "document": naive_document.model_dump(mode="json")}
    engine.remote = bridge(stub_transport({"results": [naive_result]}))
    _, naive_status = run(engine.execute(profile(), StrategyName.BM25, 2))
    assert naive_status.mode == "local-fallback"


def test_hydra_remote_miss_does_not_revive_local_memory(tmp_path: Path) -> None:
    configured = settings(tmp_path, hydradb_base_url="https://bridge.test")
    state = StateRepository(configured.state_path)
    current_profile = profile()
    state.upsert_memory(
        {
            "memory_id": "pattern:local",
            "query_pattern": current_profile.signature,
            "failure_type": FailureType.LEXICAL.value,
            "winning_strategy": StrategyName.BM25.value,
            "useful_document_ids": ["doc-1"],
            "quality": 0.9,
        }
    )
    hydra = HydraMemoryGraph(configured, state)
    hydra.remote = bridge(stub_transport({"memory": None}))

    match, status = run(hydra.find_play(current_profile))

    assert match is None
    assert status.mode == "remote"
    assert "no matching memory" in status.detail.lower()


@pytest.mark.parametrize(
    "remote_memory",
    [
        {
            "memory_id": "pattern:wrong",
            "query_pattern": "semantic_question:other",
            "failure_type": "lexical_failure",
            "winning_strategy": "bm25",
            "similarity": 0.99,
            "successful_runs": 3,
        },
        {
            "memory_id": "pattern:low",
            "query_pattern": "exact_identifier_troubleshooting:authentication",
            "failure_type": "lexical_failure",
            "winning_strategy": "bm25",
            "similarity": 0.1,
            "successful_runs": 3,
        },
    ],
)
def test_hydra_rejects_wrong_signature_or_low_confidence(
    tmp_path: Path, remote_memory: dict[str, Any]
) -> None:
    configured = settings(tmp_path, hydradb_base_url="https://bridge.test")
    state = StateRepository(configured.state_path)
    hydra = HydraMemoryGraph(configured, state)
    hydra.remote = bridge(stub_transport({"memory": remote_memory}))

    match, status = run(hydra.find_play(profile()))

    assert match is None
    assert status.mode == "local-fallback"


def test_cognee_uses_signature_and_rejects_poisoned_remote_identity(tmp_path: Path) -> None:
    configured = settings(tmp_path, cognee_base_url="https://bridge.test")
    corpus, strategy_run, diagnosis = winner(tmp_path)
    current_profile = profile()
    constructor = CogneeMemoryConstructor(configured)
    poisoned = {
        "acknowledged": True,
        "memory": {
            "memory_id": "attacker-key",
            "query_pattern": current_profile.signature,
            "failure_type": diagnosis.failure_type.value,
            "winning_strategy": StrategyName.DENSE.value,
            "useful_document_ids": [corpus.documents[-1].id],
        },
    }
    constructor.remote = bridge(stub_transport(poisoned))

    memory, status = run(constructor.construct(current_profile, diagnosis, strategy_run))

    expected_id = hashlib.sha256(current_profile.signature.encode("utf-8")).hexdigest()[:16]
    assert memory["memory_id"] == f"pattern:{expected_id}"
    assert memory["winning_strategy"] == strategy_run.strategy.value
    assert set(memory["useful_document_ids"]).issubset(
        {item.document.id for item in strategy_run.results[:3]}
    )
    assert status.mode == "local-fallback"


def test_cognee_accepts_only_acknowledged_grounded_enrichment(tmp_path: Path) -> None:
    configured = settings(tmp_path, cognee_base_url="https://bridge.test")
    _corpus, strategy_run, diagnosis = winner(tmp_path)
    current_profile = profile()
    constructor = CogneeMemoryConstructor(configured)
    stable_id = hashlib.sha256(current_profile.signature.encode("utf-8")).hexdigest()[:16]
    candidate = {
        "memory_id": f"pattern:{stable_id}",
        "query_pattern": current_profile.signature,
        "failure_type": diagnosis.failure_type.value,
        "winning_strategy": strategy_run.strategy.value,
        "useful_document_ids": [strategy_run.results[0].document.id],
        "relationships": [
            [current_profile.signature, "SOLVED_BY", strategy_run.strategy.value]
        ],
    }
    constructor.remote = bridge(
        stub_transport({"acknowledged": True, "memory": candidate})
    )

    memory, status = run(constructor.construct(current_profile, diagnosis, strategy_run))

    assert status.mode == "remote"
    assert [current_profile.signature, "SOLVED_BY", strategy_run.strategy.value] in memory[
        "relationships"
    ]
    assert set(memory["useful_document_ids"]) == {
        item.document.id for item in strategy_run.results[:3]
    }


def test_rocketride_plan_deduplicates_and_ignores_unhashable_values(tmp_path: Path) -> None:
    configured = settings(tmp_path, rocketride_base_url="https://bridge.test")
    orchestrator = RocketRideOrchestrator(configured)
    orchestrator.remote = bridge(
        stub_transport(
            {
                "strategies": [
                    {"bad": []},
                    "bm25",
                    "bm25",
                    "hybrid_rerank",
                    "hybrid",
                    "freshness",
                    "dense",
                    "bm25",
                ]
            }
        )
    )
    diagnosis = Diagnosis(
        failure_type=FailureType.LEXICAL,
        confidence=0.8,
        explanation="test",
        signals=diagnose(profile(), []).signals,
    )

    plan, status = run(orchestrator.plan(profile(), diagnosis))

    assert plan == [StrategyName.BM25, StrategyName.HYBRID_RERANK, StrategyName.HYBRID]
    assert len(plan) == len(set(plan))
    assert status.mode == "remote"


def test_rote_recall_requires_matching_key_version_and_steps(tmp_path: Path) -> None:
    configured = settings(tmp_path, rote_base_url="https://bridge.test")
    state = StateRepository(configured.state_path)
    current_profile = profile()
    state.capture_play(current_profile.signature, StrategyName.BM25, ["local-step"])
    rote = RotePlaybook(configured, state)
    rote.remote = bridge(
        stub_transport(
            {
                "play": {
                    "key": "other-pattern",
                    "strategy": "dense",
                    "steps": ["attacker-step"],
                    "version": 999,
                }
            }
        )
    )
    local, status = run(rote.recall(current_profile.signature))
    assert local is not None
    assert local["strategy"] is StrategyName.BM25
    assert status.mode == "local-fallback"

    rote.remote = bridge(
        stub_transport(
            {
                "play": {
                    "key": current_profile.signature,
                    "strategy": "hybrid",
                    "steps": ["validated-step"],
                    "version": 2,
                }
            }
        )
    )
    remote_play, remote_status = run(rote.recall(current_profile.signature))
    assert remote_play is not None
    assert remote_play["strategy"] is StrategyName.HYBRID
    assert remote_play["version"] == 2
    assert remote_status.mode == "remote"


def test_writes_require_explicit_acknowledgement(tmp_path: Path) -> None:
    configured = settings(
        tmp_path,
        hydradb_base_url="https://bridge.test",
        rote_base_url="https://bridge.test",
        cognee_base_url="https://bridge.test",
    )
    state = StateRepository(configured.state_path)
    current_profile = profile()
    memory = {
        "memory_id": "pattern:test",
        "query_pattern": current_profile.signature,
        "failure_type": FailureType.LEXICAL.value,
        "winning_strategy": StrategyName.BM25.value,
        "useful_document_ids": ["doc-1"],
        "quality": 0.8,
    }
    hydra = HydraMemoryGraph(configured, state)
    hydra.remote = bridge(stub_transport({}))
    hydra_status = run(hydra.write(memory, promoted=True))
    assert hydra_status.mode == "local-fallback"
    assert state.find_memory(current_profile.signature) is not None

    _, strategy_run, _ = winner(tmp_path)
    rote = RotePlaybook(configured, state)
    rote.remote = bridge(stub_transport({}))
    rote_status = run(rote.capture(current_profile.signature, strategy_run))
    assert rote_status.mode == "local-fallback"


def test_replay_status_exposes_local_execution_and_requires_ack(tmp_path: Path) -> None:
    configured = settings(tmp_path, rocketride_base_url="https://bridge.test")
    orchestrator = RocketRideOrchestrator(configured)
    current_profile = profile()
    play = {
        "query_pattern": current_profile.signature,
        "strategy": StrategyName.BM25,
        "version": 1,
        "steps": ["validated-step"],
    }
    orchestrator.remote = bridge(stub_transport({}))
    fallback = run(orchestrator.execute_play(current_profile, play))
    assert fallback.mode == "local-fallback"
    assert "local hotdata" in fallback.detail.lower()

    orchestrator.remote = bridge(stub_transport({"acknowledged": True}))
    accepted = run(orchestrator.execute_play(current_profile, play))
    assert accepted.mode == "remote+local-execution"
    assert "local" in accepted.detail.lower()
