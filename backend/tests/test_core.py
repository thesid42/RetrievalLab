from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import Document, QualitySignals, SearchResult, StrategyName, StrategyRun
from app.services.analyzer import calculate_signals
from app.services.engine import RetrievalEngine
from app.services.query import understand_query
from app.services.retrieval import Corpus
from app.services.state import StateRepository

CORPUS = Path(__file__).parents[1] / "app" / "data" / "corpus.json"


def test_analyzer_uses_result_position_and_text_not_untrusted_score() -> None:
    profile = understand_query("Why does AUTH-431 happen?")
    document = Document(
        id="auth-431", title="AUTH-431", content="AUTH-431 requires case-insensitive SSO mapping.",
        product="authentication", published_at=datetime(2026, 8, 1, tzinfo=UTC),
        document_type="incident", tags=["AUTH-431"],
    )
    unrelated = document.model_copy(
        update={
            "id": "guide", "title": "Generic Guide", "content": "General setup information.",
            "tags": [],
        }
    )
    # Deliberately lie in ranks and scores. Analyzer must use list position and
    # evidence text, not a strategy-normalized score or rank as an array index.
    results = [
        SearchResult(document=unrelated, score=1, rank=99, strategy=StrategyName.DENSE),
        SearchResult(document=document, score=1, rank=1, strategy=StrategyName.DENSE),
    ]
    signals = calculate_signals(profile, results)
    assert signals.exact_token_recall == 0.5
    assert signals.semantic_relevance < 1


def test_demo_fault_injection_is_opt_in() -> None:
    profile = understand_query("Why does AUTH-431 happen after enabling SSO?")
    normal = Corpus(CORPUS)
    demo = Corpus(CORPUS, demo_mode=True)
    normal_ids = [item.document.id for item in normal.search(profile, StrategyName.DENSE, 5)]
    demo_ids = [item.document.id for item in demo.search(profile, StrategyName.DENSE, 5)]
    assert "auth-431" in normal_ids
    assert "auth-431" not in demo_ids


def test_play_recall_is_read_only_and_replay_count_is_actual() -> None:
    with TemporaryDirectory() as directory:
        repository = StateRepository(Path(directory) / "state.db", corpus_version="v1")
        repository.capture_play("exact:authentication", StrategyName.HYBRID, ["search"])
        assert repository.get_play("exact:authentication")["replay_count"] == 0
        assert repository.get_play("exact:authentication")["replay_count"] == 0
        repository.record_replay("exact:authentication")
        assert repository.get_play("exact:authentication")["replay_count"] == 1


def test_archived_current_source_cannot_produce_success_or_answer() -> None:
    profile = understand_query("What is the current refund policy?")
    document = Document(
        id="old-policy", title="Refund Policy Archived", content="Full refund in 30 days.",
        product="billing", published_at=datetime(2024, 1, 1, tzinfo=UTC),
        document_type="policy", tags=["refund", "archived"],
    )
    signals = QualitySignals(
        exact_token_recall=1, semantic_relevance=1, evidence_coverage=1,
        diversity=1, metadata_match=1, freshness=1,
    )
    run = StrategyRun(
        strategy=StrategyName.DENSE,
        results=[SearchResult(document=document, score=1, rank=1, strategy=StrategyName.DENSE)],
        quality_score=1, latency_ms=1, signals=signals,
    )
    assert not RetrievalEngine._valid_retrieval(profile, run)
    assert RetrievalEngine._grounded_answer(profile, run).startswith(
        "I could not find enough reliable evidence"
    )


def test_exact_retrieval_requires_every_requested_identifier() -> None:
    profile = understand_query("Compare AUTH-431 and AUTH-502 failures")
    document = Document(
        id="auth-431", title="AUTH-431", content="AUTH-431 is an SSO mapping failure.",
        product="authentication", published_at=datetime(2026, 8, 1, tzinfo=UTC),
        document_type="incident", tags=["AUTH-431"],
    )
    signals = QualitySignals(
        exact_token_recall=0.5, semantic_relevance=1, evidence_coverage=1,
        diversity=1, metadata_match=1, freshness=1,
    )
    run = StrategyRun(
        strategy=StrategyName.HYBRID,
        results=[SearchResult(document=document, score=1, rank=1, strategy=StrategyName.HYBRID)],
        quality_score=1, latency_ms=1, signals=signals,
    )
    assert not RetrievalEngine._valid_retrieval(profile, run)


def test_multi_identifier_answer_includes_each_grounded_remedy() -> None:
    profile = understand_query("Compare AUTH-431 and AUTH-502 failures")
    first = Document(
        id="auth-431", title="AUTH-431", content=(
            "AUTH-431 occurs after enabling SSO when group casing differs. "
            "Enable case-insensitive group matching and refresh the session."
        ), product="authentication", published_at=datetime(2026, 8, 1, tzinfo=UTC),
        document_type="incident", tags=["AUTH-431"],
    )
    second = Document(
        id="auth-502", title="AUTH-502", content=(
            "AUTH-502 occurs after OAuth login when clocks drift. "
            "Synchronize application nodes with NTP and retry after tokens expire."
        ), product="authentication", published_at=datetime(2026, 8, 12, tzinfo=UTC),
        document_type="incident", tags=["AUTH-502"],
    )
    signals = QualitySignals(
        exact_token_recall=1, semantic_relevance=1, evidence_coverage=1,
        diversity=1, metadata_match=1, freshness=1,
    )
    run = StrategyRun(
        strategy=StrategyName.HYBRID,
        results=[
            SearchResult(document=first, score=1, rank=1, strategy=StrategyName.HYBRID),
            SearchResult(document=second, score=1, rank=2, strategy=StrategyName.HYBRID),
        ],
        quality_score=1, latency_ms=1, signals=signals,
    )
    answer = RetrievalEngine._grounded_answer(profile, run)
    assert "case-insensitive group matching" in answer
    assert "Synchronize application nodes with NTP" in answer


def test_memory_is_scoped_to_corpus_version() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "state.db"
        payload = {
            "memory_id": "pattern:1", "query_pattern": "exact:authentication",
            "failure_type": "lexical_failure", "winning_strategy": "hybrid",
            "useful_document_ids": [],
        }
        StateRepository(path, corpus_version="v1").upsert_memory(payload)
        assert StateRepository(path, corpus_version="v1").find_memory("exact:authentication")
        assert StateRepository(path, corpus_version="v2").find_memory("exact:authentication") is None


def test_create_app_uses_explicit_settings_and_auth_guard() -> None:
    with TemporaryDirectory() as directory:
        settings = Settings(
            _env_file=None, state_path=Path(directory) / "state.db", demo_mode=False,
            api_access_key="test-key", corpus_path=CORPUS,
        )
        with TestClient(create_app(settings)) as client:
            assert client.get("/api/v1/health").status_code == 200
            assert client.get("/api/v1/dashboard").status_code == 401
            assert client.get("/api/v1/dashboard", headers={"X-API-Key": "test-key"}).status_code == 200
