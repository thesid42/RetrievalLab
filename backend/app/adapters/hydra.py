"""Native HydraDB memory adapter.

This adapter uses the current HydraDB REST contract (not the historical
Cypher-shaped bridge): ``POST /memories/add_memory`` for ingestion and
``POST /recall/recall_preferences`` for recall.  Hydra's add endpoint queues
processing, so a successful write is reported as submitted rather than as an
already queryable memory.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from typing import Any

import httpx

from app.models import (
    FailureType,
    IntegrationStatus,
    MemoryMatch,
    QueryProfile,
    StrategyName,
)
from app.services.state import StateRepository

MAX_TEXT_LENGTH = 512
MAX_DOCUMENTS = 256
MAX_MEMORY_SUCCESSFUL_RUNS = 1_000_000_000


@dataclass(frozen=True)
class NativeHTTPResult:
    ok: bool
    attempted: bool
    detail: str
    data: dict[str, Any] | None = None
    status_code: int | None = None


class NativeHTTP:
    """HTTP transport for the documented HydraDB JSON API."""

    def __init__(
        self,
        base_url: str | None,
        api_key: str | None,
        tenant_id: str | None,
        *,
        sub_tenant_id: str | None = None,
        timeout: float = 12.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        normalized = base_url.strip().rstrip("/") if isinstance(base_url, str) else ""
        self.base_url = normalized or None
        self.api_key = api_key.strip() if isinstance(api_key, str) and api_key.strip() else None
        self.tenant_id = tenant_id.strip() if isinstance(tenant_id, str) and tenant_id.strip() else None
        self.sub_tenant_id = (
            sub_tenant_id.strip()
            if isinstance(sub_tenant_id, str) and sub_tenant_id.strip()
            else None
        )
        self.timeout = timeout
        self.transport = transport

    @property
    def configured(self) -> bool:
        # Hydra requires all three values before a request is valid. In
        # particular, do not probe the public default host without a tenant.
        return bool(self.base_url and self.api_key and self.tenant_id)

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def _scope(self) -> dict[str, str]:
        payload = {"tenant_id": self.tenant_id or ""}
        if self.sub_tenant_id:
            payload["sub_tenant_id"] = self.sub_tenant_id
        return payload

    async def post(self, path: str, payload: dict[str, Any]) -> NativeHTTPResult:
        if not self.configured:
            return NativeHTTPResult(
                False,
                False,
                "HydraDB endpoint, API key, and tenant_id are required; local fallback used.",
            )
        if not isinstance(payload, dict):
            return NativeHTTPResult(False, False, "Invalid HydraDB request payload; local fallback used.")
        kwargs: dict[str, Any] = {"timeout": self.timeout}
        if self.transport is not None:
            kwargs["transport"] = self.transport
        try:
            async with httpx.AsyncClient(**kwargs) as client:
                response = await client.post(
                    f"{self.base_url}{path}", json=payload, headers=self._headers()
                )
                status_code = response.status_code
                if not response.is_success:
                    return NativeHTTPResult(
                        False,
                        True,
                        f"HydraDB returned HTTP {status_code}; local fallback used.",
                        status_code=status_code,
                    )
                if not response.content:
                    return NativeHTTPResult(
                        False,
                        True,
                        "HydraDB returned an empty response; local fallback used.",
                        status_code=status_code,
                    )
                data = response.json()
        except (httpx.HTTPError, TypeError, ValueError) as error:
            return NativeHTTPResult(
                False,
                True,
                f"HydraDB unavailable or returned invalid JSON ({type(error).__name__}); local fallback used.",
            )
        if not isinstance(data, dict):
            return NativeHTTPResult(
                False,
                True,
                "HydraDB returned a JSON value instead of an object; local fallback used.",
                status_code=status_code,
            )
        return NativeHTTPResult(True, True, "HydraDB returned a valid response.", data, status_code)


def _setting(settings: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        value = getattr(settings, name, None)
        if value is not None:
            return value
    return default


def _status(
    mode: str,
    called: bool,
    detail: str,
    *,
    role: str = "durable graph recall",
) -> IntegrationStatus:
    return IntegrationStatus(
        name="HydraDB",
        role=role,
        mode=mode,
        called=called,
        detail=detail,
    )


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
        value = memory[key]
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT_LENGTH:
            return False
    try:
        FailureType(memory["failure_type"])
        StrategyName(memory["winning_strategy"])
    except (TypeError, ValueError):
        return False
    document_ids = memory["useful_document_ids"]
    if (
        not isinstance(document_ids, list)
        or len(document_ids) > MAX_DOCUMENTS
        or any(
            not isinstance(document_id, str)
            or not document_id.strip()
            or len(document_id) > MAX_TEXT_LENGTH
            for document_id in document_ids
        )
    ):
        return False
    quality = memory.get("quality")
    if quality is not None and (
        isinstance(quality, bool)
        or not isinstance(quality, (int, float))
        or not math.isfinite(float(quality))
        or not 0 <= float(quality) <= 1
    ):
        return False
    corpus_version = memory.get("corpus_version")
    return not (
        corpus_version is not None
        and (
            not isinstance(corpus_version, str)
            or not corpus_version.strip()
            or len(corpus_version) > MAX_TEXT_LENGTH
        )
    )


def _memory_item(memory: dict[str, Any]) -> dict[str, Any]:
    """Encode one canonical RetrievalLab memory as a Hydra MemoryItem."""

    canonical = {
        key: memory[key]
        for key in (
            "memory_id",
            "query_pattern",
            "failure_type",
            "winning_strategy",
            "useful_document_ids",
            "quality",
            "corpus_version",
        )
        if key in memory
    }
    # Hydra's source_id is the idempotency key documented for upsert behavior.
    return {
        "text": json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "infer": False,
        "source_id": memory["memory_id"],
        "title": f"RetrievalLab memory {memory['memory_id']}",
        "metadata": {
            "retrievallab_memory_id": memory["memory_id"],
            "query_pattern": memory["query_pattern"],
            "corpus_version": memory.get("corpus_version"),
        },
        "additional_metadata": {"source": "retrievallab"},
    }


def _canonical_memory_id(query_pattern: str) -> str:
    return f"pattern:{hashlib.sha256(query_pattern.encode('utf-8')).hexdigest()[:16]}"


def _queued_success(data: dict[str, Any] | None, memory_id: str) -> bool:
    """Validate Hydra's success + per-item queue acknowledgement."""

    if not isinstance(data, dict) or data.get("success") is not True:
        return False
    success_count = data.get("success_count")
    results = data.get("results")
    if not isinstance(results, list):
        return False
    if (
        success_count is not None
        and (
            isinstance(success_count, bool)
            or not isinstance(success_count, int)
            or success_count <= 0
        )
    ):
        return False
    for result in results:
        if not isinstance(result, dict):
            continue
        if result.get("source_id") == memory_id and result.get("status") in {
            "queued",
            "processing",
            "completed",
        }:
            return True
    return False


def _candidate_from_chunk(chunk: dict[str, Any]) -> dict[str, Any] | None:
    """Extract only a JSON object we intentionally wrote to Hydra."""

    for key in ("metadata", "additional_metadata"):
        metadata = chunk.get(key)
        if isinstance(metadata, dict):
            direct = metadata.get("retrievallab_memory")
            if isinstance(direct, dict):
                return direct
            if all(
                field in metadata
                for field in ("memory_id", "query_pattern", "failure_type", "winning_strategy")
            ):
                return metadata
    for key in ("chunk_content", "content", "text"):
        content = chunk.get(key)
        if not isinstance(content, str):
            continue
        try:
            parsed = json.loads(content)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict):
            return parsed.get("memory") if isinstance(parsed.get("memory"), dict) else parsed
    return None


def _remote_memory(
    chunk: dict[str, Any], profile: QueryProfile, threshold: float, expected_corpus: str | None
) -> MemoryMatch | None:
    candidate = _candidate_from_chunk(chunk)
    if not isinstance(candidate, dict):
        return None
    if not _valid_memory_payload(candidate):
        return None
    if candidate["query_pattern"] != profile.signature:
        return None
    if candidate["memory_id"] != _canonical_memory_id(profile.signature):
        return None
    source_id = chunk.get("source_id")
    if source_id is not None and source_id != candidate["memory_id"]:
        return None
    if expected_corpus and expected_corpus != "unknown" and candidate.get("corpus_version") != expected_corpus:
        return None
    similarity = chunk.get("relevancy_score", chunk.get("similarity", chunk.get("score")))
    if (
        isinstance(similarity, bool)
        or not isinstance(similarity, (int, float))
        or not math.isfinite(float(similarity))
        or not 0 <= float(similarity) <= 1
        or float(similarity) < threshold
    ):
        return None
    successful_runs = candidate.get("successful_runs", 1)
    if (
        isinstance(successful_runs, bool)
        or not isinstance(successful_runs, int)
        or not 0 < successful_runs <= MAX_MEMORY_SUCCESSFUL_RUNS
    ):
        return None
    try:
        return MemoryMatch(
            memory_id=candidate["memory_id"],
            query_pattern=candidate["query_pattern"],
            failure_type=FailureType(candidate["failure_type"]),
            winning_strategy=StrategyName(candidate["winning_strategy"]),
            similarity=float(similarity),
            successful_runs=successful_runs,
        )
    except (TypeError, ValueError):
        return None


class HydraMemoryGraph:
    """Recall and write RetrievalLab memories through HydraDB's native API."""

    def __init__(
        self,
        settings: Any,
        state: StateRepository,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.state = state
        configured_threshold = _setting(settings, "memory_similarity_threshold", default=0.58)
        try:
            threshold = float(configured_threshold)
        except (TypeError, ValueError):
            threshold = 0.58
        self.similarity_threshold = threshold if math.isfinite(threshold) and 0 <= threshold <= 1 else 0.58
        base_url = _setting(
            settings,
            "hydradb_api_url",
            default="https://api.hydradb.com",
        )
        self.remote = NativeHTTP(
            base_url,
            _setting(settings, "hydradb_api_key"),
            _setting(settings, "hydradb_tenant_id"),
            sub_tenant_id=_setting(settings, "hydradb_sub_tenant_id"),
            timeout=_setting(settings, "request_timeout_seconds", default=12.0),
            transport=transport,
        )

    def _local(self, profile: QueryProfile) -> MemoryMatch | None:
        try:
            return self.state.find_memory(profile.signature)
        except (TypeError, ValueError):
            return None

    async def find_play(self, profile: QueryProfile) -> tuple[MemoryMatch | None, IntegrationStatus]:
        local = self._local(profile)
        if not self.remote.configured:
            return local, _status(
                "local-fallback",
                False,
                "HydraDB is not fully configured; local SQLite memory mirror used.",
            )
        remote = await self.remote.post(
            "/recall/recall_preferences",
            {
                **self.remote._scope(),
                "query": profile.signature,
                "mode": "thinking",
            },
        )
        if not remote.ok:
            return local, _status("local-fallback", remote.attempted, remote.detail)
        chunks = remote.data.get("chunks") if remote.data else None
        if not isinstance(chunks, list):
            return local, _status(
                "local-fallback",
                True,
                "HydraDB recall response omitted its chunks list; local SQLite mirror used.",
            )
        # A valid empty recall is authoritative. Do not revive a stale local
        # match after Hydra has answered the query successfully.
        if not chunks:
            return None, _status("remote", True, "HydraDB returned no matching memory.")
        expected_corpus = getattr(self.state, "corpus_version", None)
        candidates = [
            match
            for chunk in chunks[:128]
            if isinstance(chunk, dict)
            for match in [_remote_memory(chunk, profile, self.similarity_threshold, expected_corpus)]
            if match is not None
        ]
        if candidates:
            return max(candidates, key=lambda match: match.similarity), _status(
                "remote", True, "HydraDB returned a validated memory for this query signature."
            )
        return None, _status(
            "remote",
            True,
            "HydraDB returned chunks, but none matched the canonical signature/corpus contract.",
        )

    async def write(self, memory: dict[str, Any], *, promoted: bool) -> IntegrationStatus:
        if not _valid_memory_payload(memory) or memory.get("memory_id") != _canonical_memory_id(
            memory.get("query_pattern", "")
        ):
            return _status(
                "error-fallback",
                False,
                "Rejected invalid memory payload; no HydraDB write or SQLite promotion occurred.",
                role="durable graph write",
            )
        if not promoted:
            return _status(
                "local-fallback",
                False,
                "Memory was not promoted by the quality gate; HydraDB memory write skipped.",
                role="durable graph write",
            )
        # Keep the local SQLite mirror as the explicit application fallback even
        # when HydraDB is configured. Never let remote queueing replace local
        # validation or promotion semantics.
        try:
            self.state.upsert_memory(memory)
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return _status(
                "error-fallback",
                False,
                "SQLite memory mirror could not be updated; HydraDB write was not attempted.",
                role="durable graph write",
            )
        if not self.remote.configured:
            return _status(
                "local-fallback",
                False,
                "HydraDB is not fully configured; promoted memory is available in local SQLite only.",
                role="durable graph write",
            )
        remote = await self.remote.post(
            "/memories/add_memory",
            {
                **self.remote._scope(),
                "memories": [_memory_item(memory)],
                "upsert": True,
            },
        )
        if not remote.ok:
            return _status(
                "local-fallback",
                remote.attempted,
                remote.detail,
                role="durable graph write",
            )
        if not _queued_success(remote.data, memory["memory_id"]):
            return _status(
                "local-fallback",
                True,
                "HydraDB response did not acknowledge queueing this memory; local SQLite remains authoritative.",
                role="durable graph write",
            )
        return _status(
            "remote-submitted",
            True,
            "HydraDB queued the memory for ingestion; remote queryability is pending processing. Local SQLite mirror updated.",
            role="durable graph write",
        )
