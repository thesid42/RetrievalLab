from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings
from app.models import (
    Diagnosis,
    FailureType,
    IntegrationStatus,
    MemoryMatch,
    QueryProfile,
    StrategyName,
    StrategyRun,
)
from app.services.security import redact_sensitive
from app.services.state import StateRepository

MAX_PLAN_STRATEGIES = len(StrategyName)
MAX_PLAY_STEPS = 64
MAX_RELATIONSHIPS = 256
MAX_TEXT_LENGTH = 512
MAX_MEMORY_SUCCESSFUL_RUNS = 1_000_000_000
ALLOWED_RELATIONS = frozenset({"SUFFERED_FROM", "SOLVED_BY", "RETRIEVED"})


@dataclass(frozen=True)
class RemoteResult:
    """Result of a bridge request.

    ``called`` means that the bridge returned a non-empty JSON object that can be
    inspected. ``attempted`` is retained separately so integration telemetry can
    say that a network request happened without presenting an unusable response as
    a successful sponsor integration.
    """

    called: bool
    detail: str
    data: dict[str, Any] | None = None
    attempted: bool = False


class RemoteBridge:
    """Small HTTP port used by the sponsor-shaped adapters.

    This is deliberately a bridge contract, not a native sponsor SDK. Transport
    success is not enough to claim that an operation was accepted; each adapter
    validates its endpoint-specific response before selecting a ``remote`` mode.
    """

    def __init__(
        self,
        base_url: str | None,
        api_key: str | None,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if isinstance(base_url, str):
            normalized_url = base_url.strip().rstrip("/")
        else:
            normalized_url = ""
        self.base_url = normalized_url or None
        self.api_key = api_key.strip() if isinstance(api_key, str) and api_key.strip() else None
        self.timeout = timeout
        self.transport = transport

    async def post(self, path: str, payload: dict[str, Any]) -> RemoteResult:
        if not isinstance(payload, dict):
            return RemoteResult(False, "Invalid bridge payload; local adapter executed")
        if not self.base_url:
            return RemoteResult(False, "No endpoint configured; local adapter executed")

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        client_kwargs: dict[str, Any] = {"timeout": self.timeout}
        if self.transport is not None:
            client_kwargs["transport"] = self.transport
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.post(
                    f"{self.base_url}{path}", json=payload, headers=headers
                )
                response.raise_for_status()
                if not response.content:
                    return RemoteResult(
                        False,
                        "Remote returned no JSON response; local adapter executed",
                        attempted=True,
                    )
                data = response.json()
        except (httpx.HTTPError, TypeError, ValueError) as error:
            return RemoteResult(
                False,
                f"Remote unavailable or invalid response; local fallback used ({type(error).__name__})",
                attempted=True,
            )

        if not isinstance(data, dict):
            return RemoteResult(
                False,
                "Remote returned a JSON value instead of an object; local adapter executed",
                attempted=True,
            )
        return RemoteResult(True, "Remote adapter returned a valid JSON object", data, True)


def _status(
    name: str,
    role: str,
    remote: RemoteResult,
    *,
    accepted: bool,
    remote_mode: str = "remote",
    fallback_detail: str | None = None,
    accepted_detail: str | None = None,
) -> IntegrationStatus:
    """Build an honest status for a transport result and contract decision."""

    called = remote.called or remote.attempted
    if remote.called and accepted:
        return IntegrationStatus(
            name=name,
            role=role,
            mode=remote_mode,
            called=called,
            detail=accepted_detail or remote.detail,
        )
    detail = fallback_detail or "Remote response was not accepted; local fallback used."
    if remote.detail:
        detail = f"{detail} {remote.detail}"
    return IntegrationStatus(
        name=name,
        role=role,
        mode="local-fallback",
        called=called,
        detail=detail,
    )


def _acknowledged(data: dict[str, Any] | None) -> bool:
    """Require the explicit bridge acknowledgement used by write/execute ports."""

    return isinstance(data, dict) and data.get("acknowledged") is True


def _safe_relationships(
    value: Any, *, allowed_entities: set[str] | None = None
) -> list[list[str]] | None:
    if not isinstance(value, list) or len(value) > MAX_RELATIONSHIPS:
        return None
    relationships: list[list[str]] = []
    for relation in value:
        if (
            not isinstance(relation, list)
            or len(relation) != 3
            or any(
                not isinstance(part, str)
                or not part.strip()
                or len(part) > MAX_TEXT_LENGTH
                for part in relation
            )
            or relation[1] not in ALLOWED_RELATIONS
            or (
                allowed_entities is not None
                and (relation[0] not in allowed_entities or relation[2] not in allowed_entities)
            )
        ):
            return None
        relationships.append(relation)
    return relationships


def _valid_memory_payload(memory: Any) -> bool:
    if not isinstance(memory, dict):
        return False
    required = {
        "memory_id",
        "query_pattern",
        "failure_type",
        "winning_strategy",
        "useful_document_ids",
    }
    if not required.issubset(memory):
        return False
    for key in ("memory_id", "query_pattern", "failure_type", "winning_strategy"):
        if not isinstance(memory[key], str) or not memory[key].strip() or len(memory[key]) > MAX_TEXT_LENGTH:
            return False
    try:
        FailureType(memory["failure_type"])
        StrategyName(memory["winning_strategy"])
    except (TypeError, ValueError):
        return False
    document_ids = memory["useful_document_ids"]
    if (
        not isinstance(document_ids, list)
        or len(document_ids) > MAX_RELATIONSHIPS
        or any(
            not isinstance(document_id, str)
            or not document_id.strip()
            or len(document_id) > MAX_TEXT_LENGTH
            for document_id in document_ids
        )
    ):
        return False
    if "quality" in memory:
        quality = memory["quality"]
        if (
            isinstance(quality, bool)
            or not isinstance(quality, (int, float))
            or not math.isfinite(float(quality))
            or not 0 <= float(quality) <= 1
        ):
            return False
    if "relationships" in memory:
        allowed_entities = {
            memory["query_pattern"],
            memory["failure_type"],
            memory["winning_strategy"],
            *document_ids,
        }
        if _safe_relationships(memory["relationships"], allowed_entities=allowed_entities) is None:
            return False
    return True


def _valid_play(candidate: Any, query_pattern: str) -> dict[str, Any] | None:
    """Normalize and validate a local or remote deterministic play."""

    if not isinstance(candidate, dict):
        return None
    key = candidate.get("key")
    pattern = candidate.get("query_pattern")
    # A bridge may call the identity ``key`` or ``query_pattern``. If both are
    # present they must agree, and one of them must be present.
    if key is None and pattern is None:
        return None
    if key is not None and (not isinstance(key, str) or key != query_pattern):
        return None
    if pattern is not None and (not isinstance(pattern, str) or pattern != query_pattern):
        return None

    version = candidate.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= MAX_MEMORY_SUCCESSFUL_RUNS:
        return None
    strategy = candidate.get("strategy")
    if isinstance(strategy, StrategyName):
        normalized_strategy = strategy
    elif isinstance(strategy, str):
        try:
            normalized_strategy = StrategyName(strategy)
        except ValueError:
            return None
    else:
        return None
    steps = candidate.get("steps")
    if (
        not isinstance(steps, list)
        or not 0 < len(steps) <= MAX_PLAY_STEPS
        or any(
            not isinstance(step, str) or not step.strip() or len(step) > MAX_TEXT_LENGTH
            for step in steps
        )
    ):
        return None
    normalized: dict[str, Any] = {
        "query_pattern": query_pattern,
        "strategy": normalized_strategy,
        "version": version,
        "steps": list(steps),
    }
    replay_count = candidate.get("replay_count", 0)
    if (
        isinstance(replay_count, bool)
        or not isinstance(replay_count, int)
        or not 0 <= replay_count <= MAX_MEMORY_SUCCESSFUL_RUNS
    ):
        return None
    normalized["replay_count"] = replay_count
    return normalized


class HydraMemoryGraph:
    def __init__(self, settings: Settings, state: StateRepository):
        self.state = state
        self.remote = RemoteBridge(
            settings.hydradb_base_url, settings.hydradb_api_key, settings.request_timeout_seconds
        )
        configured_threshold = getattr(settings, "memory_similarity_threshold", 0.58)
        try:
            threshold = float(configured_threshold)
        except (TypeError, ValueError):
            threshold = 0.58
        self.similarity_threshold = threshold if math.isfinite(threshold) and 0 <= threshold <= 1 else 0.58

    def _remote_memory(
        self, payload: Any, profile: QueryProfile
    ) -> MemoryMatch | None:
        if not isinstance(payload, dict):
            return None
        if payload.get("query_pattern") != profile.signature:
            return None
        expected_corpus_version = getattr(self.state, "corpus_version", None)
        if (
            expected_corpus_version
            and expected_corpus_version != "unknown"
            and payload.get("corpus_version") != expected_corpus_version
        ):
            return None
        similarity = payload.get("similarity")
        if (
            isinstance(similarity, bool)
            or not isinstance(similarity, (int, float))
            or not math.isfinite(float(similarity))
            or not 0 <= float(similarity) <= 1
            or float(similarity) < self.similarity_threshold
        ):
            return None
        successful_runs = payload.get("successful_runs")
        if (
            isinstance(successful_runs, bool)
            or not isinstance(successful_runs, int)
            or not 0 < successful_runs <= MAX_MEMORY_SUCCESSFUL_RUNS
        ):
            return None
        if not isinstance(payload.get("memory_id"), str) or not payload["memory_id"].strip():
            return None
        try:
            return MemoryMatch.model_validate(payload)
        except (TypeError, ValueError):
            return None

    async def find_play(self, profile: QueryProfile) -> tuple[MemoryMatch | None, IntegrationStatus]:
        try:
            local = self.state.find_memory(profile.signature)
        except (TypeError, ValueError):
            local = None
        remote = await self.remote.post(
            "/v1/cypher",
            {
                "query": "MATCH (p:QueryPattern {id: $id})-[:SOLVED_BY]->(s:Strategy) RETURN p,s LIMIT 1",
                "parameters": {
                    "id": profile.signature,
                    "corpus_version": getattr(self.state, "corpus_version", None),
                },
            },
        )
        if not remote.called:
            return local, _status(
                "HydraDB",
                "durable graph recall",
                remote,
                accepted=False,
                fallback_detail="Queried the local graph mirror.",
            )

        assert remote.data is not None
        if "memory" not in remote.data:
            return local, _status(
                "HydraDB",
                "durable graph recall",
                remote,
                accepted=False,
                fallback_detail="Remote graph response omitted its memory field; local mirror used.",
            )
        # An explicit remote miss is authoritative for this request. Do not
        # resurrect a stale local match after a valid graph response.
        if remote.data["memory"] is None:
            return None, _status(
                "HydraDB",
                "durable graph recall",
                remote,
                accepted=True,
                fallback_detail="Remote graph reported no matching memory.",
                accepted_detail="Remote graph reported no matching memory.",
            )
        match = self._remote_memory(remote.data["memory"], profile)
        if match is not None:
            return match, _status(
                "HydraDB",
                "durable graph recall",
                remote,
                accepted=True,
            )
        return local, _status(
            "HydraDB",
            "durable graph recall",
            remote,
            accepted=False,
            fallback_detail="Remote graph memory failed signature or confidence validation; local mirror used.",
        )

    async def write(self, memory: dict[str, Any], *, promoted: bool) -> IntegrationStatus:
        if not _valid_memory_payload(memory):
            return IntegrationStatus(
                name="HydraDB",
                role="durable graph write",
                mode="local-fallback",
                called=False,
                detail="Rejected invalid memory payload; no graph write was attempted.",
            )
        if promoted:
            self.state.upsert_memory(memory)
        cypher = (
            "MERGE (p:QueryPattern {id: $query_pattern}) "
            "MERGE (f:FailureType {name: $failure_type}) "
            "MERGE (s:Strategy {name: $winning_strategy}) "
            "MERGE (p)-[:SUFFERED_FROM]->(f) MERGE (p)-[:SOLVED_BY]->(s) "
            "SET p.failure_type = $failure_type, "
            "p.winning_strategy = $winning_strategy, "
            "p.corpus_version = $corpus_version, "
            "p.successful_runs = coalesce(p.successful_runs, 0) + 1"
            if promoted
            else "MERGE (o:RunObservation {id: $memory_id}) SET o.outcome = 'not_promoted'"
        )
        remote = await self.remote.post(
            "/v1/cypher",
            {
                "query": cypher,
                "parameters": {
                    **memory,
                    "promoted": promoted,
                    "corpus_version": memory.get("corpus_version"),
                },
            },
        )
        return _status(
            "HydraDB",
            "durable graph write",
            remote,
            accepted=_acknowledged(remote.data),
            remote_mode="remote+local-mirror" if promoted else "remote",
            fallback_detail=(
                "Graph write was not explicitly acknowledged; local mirror is authoritative."
                if promoted
                else "Run-only graph observation was not explicitly acknowledged; no memory promotion occurred."
            ),
        )


class CogneeMemoryConstructor:
    def __init__(self, settings: Settings):
        self.remote = RemoteBridge(
            settings.cognee_base_url, settings.cognee_api_key, settings.request_timeout_seconds
        )

    async def construct(
        self,
        profile: QueryProfile,
        diagnosis: Diagnosis,
        winner: StrategyRun,
    ) -> tuple[dict[str, Any], IntegrationStatus]:
        # The signature, not the broad query type, is the durable identity. Two
        # domains can share a query type while requiring different retrieval plays.
        stable_id = hashlib.sha256(profile.signature.encode("utf-8")).hexdigest()[:16]
        winner_document_ids = [item.document.id for item in winner.results[:3]]
        memory = {
            "memory_id": f"pattern:{stable_id}",
            "query_pattern": profile.signature,
            "failure_type": diagnosis.failure_type.value,
            "winning_strategy": winner.strategy.value,
            "useful_document_ids": winner_document_ids,
            "quality": winner.quality_score,
            "relationships": [
                [profile.signature, "SUFFERED_FROM", diagnosis.failure_type.value],
                [profile.signature, "SOLVED_BY", winner.strategy.value],
                *[
                    [winner.strategy.value, "RETRIEVED", item.document.id]
                    for item in winner.results[:3]
                ],
            ],
        }
        corpus_version = getattr(profile, "corpus_version", None)
        if isinstance(corpus_version, str) and corpus_version.strip():
            memory["corpus_version"] = corpus_version
        remote = await self.remote.post("/v1/memories/construct", memory)
        accepted = False
        if remote.called and _acknowledged(remote.data):
            candidate = remote.data.get("memory") if remote.data else None
            if isinstance(candidate, dict):
                required = {
                    "memory_id",
                    "query_pattern",
                    "failure_type",
                    "winning_strategy",
                    "useful_document_ids",
                }
                candidate_ids = candidate.get("useful_document_ids")
                canonical_identity = (
                    candidate.get("memory_id") == memory["memory_id"]
                    and candidate.get("query_pattern") == memory["query_pattern"]
                    and candidate.get("failure_type") == memory["failure_type"]
                    and candidate.get("winning_strategy") == memory["winning_strategy"]
                    and (
                        "corpus_version" not in memory
                        or candidate.get("corpus_version") == memory["corpus_version"]
                    )
                )
                valid_ids = (
                    isinstance(candidate_ids, list)
                    and bool(candidate_ids or not winner_document_ids)
                    and len(candidate_ids) <= len(winner_document_ids)
                    and all(
                        isinstance(document_id, str)
                        and document_id in winner_document_ids
                        for document_id in candidate_ids
                    )
                )
                valid_relationships = True
                if "relationships" in candidate:
                    allowed_entities = {
                        memory["query_pattern"],
                        memory["failure_type"],
                        memory["winning_strategy"],
                        *winner_document_ids,
                    }
                    valid_relationships = (
                        _safe_relationships(
                            candidate["relationships"], allowed_entities=allowed_entities
                        )
                        is not None
                    )
                if required.issubset(candidate) and canonical_identity and valid_ids and valid_relationships:
                    # Keep canonical fields generated by this run. Remote output
                    # can add only bounded relationships grounded in this winning
                    # run; it cannot replace the memory key/strategy/evidence.
                    if "relationships" in candidate:
                        memory["relationships"] = list(
                            dict.fromkeys(
                                [
                                    tuple(relation)
                                    for relation in [
                                        *memory["relationships"],
                                        *candidate["relationships"],
                                    ]
                                ]
                            )
                        )
                        memory["relationships"] = [list(relation) for relation in memory["relationships"]]
                    accepted = True
        return memory, _status(
            "Cognee",
            "memory construction",
            remote,
            accepted=accepted,
            remote_mode="remote",
            fallback_detail="Canonical memory delta constructed locally; remote construction was not acknowledged or failed validation.",
        )


class RocketRideOrchestrator:
    def __init__(self, settings: Settings):
        self.remote = RemoteBridge(
            settings.rocketride_base_url,
            settings.rocketride_api_key,
            settings.request_timeout_seconds,
        )

    async def plan(
        self, profile: QueryProfile, diagnosis: Diagnosis
    ) -> tuple[list[StrategyName], IntegrationStatus]:
        if diagnosis.failure_type is FailureType.LEXICAL:
            strategies = [StrategyName.BM25, StrategyName.HYBRID, StrategyName.HYBRID_RERANK]
        elif diagnosis.failure_type is FailureType.STALE:
            strategies = [StrategyName.HYBRID, StrategyName.FRESHNESS, StrategyName.HYBRID_RERANK]
        elif diagnosis.failure_type is FailureType.NONE:
            strategies = [StrategyName.DENSE]
        else:
            strategies = [StrategyName.BM25, StrategyName.HYBRID, StrategyName.HYBRID_RERANK]
        payload = {
            "query": redact_sensitive(profile.raw_query),
            "diagnosis": diagnosis.model_dump(mode="json"),
            "registered_tools": [item.value for item in strategies],
        }
        remote = await self.remote.post("/v1/executions/plan", payload)
        accepted = False
        if remote.called and isinstance(remote.data, dict) and isinstance(remote.data.get("strategies"), list):
            allowed = {item.value for item in strategies}
            proposed: list[StrategyName] = []
            seen: set[str] = set()
            # Truncate before processing so an untrusted bridge cannot return an
            # unbounded execution plan. Ignore non-string/unknown entries without
            # ever using them as set keys.
            for value in remote.data["strategies"][:MAX_PLAN_STRATEGIES]:
                if not isinstance(value, str) or value not in allowed or value in seen:
                    continue
                seen.add(value)
                proposed.append(StrategyName(value))
            if proposed:
                strategies = proposed
                accepted = True
        return strategies, _status(
            "RocketRide",
            "advisor and tool orchestration",
            remote,
            accepted=accepted,
            fallback_detail="Created a registered-tool plan locally; remote plan was not accepted.",
        )

    async def execute_play(self, profile: QueryProfile, play: dict[str, Any]) -> IntegrationStatus:
        normalized_play = _valid_play(play, profile.signature)
        if normalized_play is None:
            return IntegrationStatus(
                name="RocketRide",
                role="deterministic play execution",
                mode="local-fallback",
                called=False,
                detail="Rejected invalid play before bridge dispatch; local hotdata execution remains authoritative.",
            )
        remote = await self.remote.post(
            "/v1/executions/replay",
            {
                "query": redact_sensitive(profile.raw_query),
                "play": {
                    **normalized_play,
                    "strategy": normalized_play["strategy"].value,
                },
            },
        )
        return _status(
            "RocketRide",
            "deterministic play execution",
            remote,
            accepted=_acknowledged(remote.data),
            remote_mode="remote+local-execution",
            fallback_detail="Replay bridge was not explicitly acknowledged; local hotdata execution remains authoritative.",
            accepted_detail="Remote bridge acknowledged replay dispatch; local hotdata execution remains authoritative for normalized results.",
        )


class RotePlaybook:
    def __init__(self, settings: Settings, state: StateRepository):
        self.state = state
        self.remote = RemoteBridge(
            settings.rote_base_url, settings.rote_api_key, settings.request_timeout_seconds
        )

    async def recall(self, query_pattern: str) -> tuple[dict[str, Any] | None, IntegrationStatus]:
        try:
            local_raw = self.state.get_play(query_pattern)
        except (TypeError, ValueError):
            local_raw = None
        local = _valid_play(local_raw, query_pattern)
        remote = await self.remote.post("/v1/plays/lookup", {"key": query_pattern})
        if remote.called and isinstance(remote.data, dict) and "play" in remote.data:
            candidate = remote.data["play"]
            if isinstance(candidate, dict):
                normalized = _valid_play(candidate, query_pattern)
                if normalized is not None:
                    return normalized, _status(
                        "Modiqo Rote",
                        "muscle-memory replay",
                        remote,
                        accepted=True,
                    )
                return local, _status(
                    "Modiqo Rote",
                    "muscle-memory replay",
                    remote,
                    accepted=False,
                    fallback_detail="Remote play failed key, version, or step validation; local mirror used.",
                )
            if candidate is None:
                return None, _status(
                    "Modiqo Rote",
                    "muscle-memory replay",
                    remote,
                    accepted=True,
                    accepted_detail="Remote play lookup reported no matching play.",
                    fallback_detail="Remote play lookup reported a miss; no local play was revived.",
                )
        return local, _status(
            "Modiqo Rote",
            "muscle-memory replay",
            remote,
            accepted=False,
            fallback_detail=(
                "Loaded a deterministic local play."
                if local
                else "No validated captured play found."
            ),
        )

    async def capture(self, query_pattern: str, winner: StrategyRun) -> IntegrationStatus:
        steps = [
            "validate_query_parameters",
            f"execute_{winner.strategy.value}",
            "normalize_candidates",
            "score_evidence",
            "return_top_evidence",
        ]
        self.state.capture_play(query_pattern, winner.strategy, steps)
        remote = await self.remote.post(
            "/v1/plays/capture",
            {
                "key": query_pattern,
                "strategy": winner.strategy.value,
                "steps": steps,
                "quality_gate": winner.quality_score,
            },
        )
        return _status(
            "Modiqo Rote",
            "successful workflow capture",
            remote,
            accepted=_acknowledged(remote.data),
            remote_mode="remote+local-mirror",
            fallback_detail="Captured a versioned deterministic play locally; remote capture was not acknowledged.",
        )
