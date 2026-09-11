from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class StrategyName(StrEnum):
    DENSE = "dense"
    BM25 = "bm25"
    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid_rerank"
    FRESHNESS = "freshness"


class FailureType(StrEnum):
    NONE = "none"
    LEXICAL = "lexical_failure"
    SEMANTIC = "semantic_failure"
    METADATA = "metadata_failure"
    STALE = "stale_retrieval"
    REDUNDANT = "redundant_results"
    INSUFFICIENT = "insufficient_evidence"
    POOR_RANKING = "poor_ranking"


class RunOutcome(StrEnum):
    SUCCESS = "success"
    DEGRADED = "degraded"


class Document(BaseModel):
    id: str
    title: str
    content: str
    product: str
    version: str | None = None
    published_at: datetime
    document_type: str
    tags: list[str] = Field(default_factory=list)

    @field_validator("id", "title", "content", "product", "document_type")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("document text fields cannot be blank")
        return value

    @field_validator("published_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("published_at must include a timezone")
        return value.astimezone(UTC)


class SearchResult(BaseModel):
    document: Document
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    rank: int = Field(ge=1)
    strategy: StrategyName
    reasons: list[str] = Field(default_factory=list)


class QueryProfile(BaseModel):
    raw_query: str
    normalized_query: str
    query_type: str
    signature: str
    domain: str
    exact_identifiers: list[str] = Field(default_factory=list)
    current_intent: bool = False
    terms: list[str] = Field(default_factory=list)

    @field_validator("raw_query", "normalized_query", "query_type", "signature", "domain")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query profile fields cannot be blank")
        return value


class QualitySignals(BaseModel):
    exact_token_recall: float = Field(ge=0, le=1)
    semantic_relevance: float = Field(ge=0, le=1)
    evidence_coverage: float = Field(ge=0, le=1)
    diversity: float = Field(ge=0, le=1)
    metadata_match: float = Field(ge=0, le=1)
    freshness: float = Field(ge=0, le=1)


class Diagnosis(BaseModel):
    failure_type: FailureType
    confidence: float = Field(ge=0, le=1)
    explanation: str
    signals: QualitySignals


class StrategyRun(BaseModel):
    strategy: StrategyName
    results: list[SearchResult]
    quality_score: float = Field(ge=0, le=1)
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    signals: QualitySignals


class MemoryMatch(BaseModel):
    memory_id: str
    query_pattern: str
    failure_type: FailureType
    winning_strategy: StrategyName
    similarity: float = Field(ge=0, le=1, allow_inf_nan=False)
    successful_runs: int = Field(ge=1)


class IntegrationStatus(BaseModel):
    name: str
    role: str
    mode: str
    called: bool
    detail: str


class RetrievalRunRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    force_discovery: bool = False
    top_k: int = Field(default=5, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def query_must_have_content(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 3:
            raise ValueError("query must contain at least three non-whitespace characters")
        return value


class RetrievalRunResponse(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=utc_now)
    query: str
    query_profile: QueryProfile
    path: Literal["discovery", "replay"]
    memory_match: MemoryMatch | None = None
    baseline: StrategyRun
    baseline_skipped: bool = False
    diagnosis: Diagnosis
    experiments: list[StrategyRun]
    winner: StrategyRun
    answer: str
    evidence: list[SearchResult]
    planner_calls: int
    retrieval_attempts: int
    elapsed_ms: float
    integrations: list[IntegrationStatus]
    trace: list[str]
    outcome: RunOutcome = RunOutcome.DEGRADED
    memory_promoted: bool = False
    play_captured: bool = False
    replay_attempted: bool = False
    quality_lift: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)
    demo_mode: bool = False


class DashboardSummary(BaseModel):
    total_runs: int
    discovery_runs: int
    replay_runs: int
    patterns_learned: int
    memory_hit_rate: float
    average_attempts_discovery: float
    average_attempts_replay: float
    recent_runs: list[dict[str, Any]]
    average_quality_lift: float | None = None
    attempts_saved_percent: float | None = None
    latency_saved_percent: float | None = None
    quality_history: list[dict[str, Any]] = Field(default_factory=list)
