"""Native Cognee Cloud/self-hosted memory adapter.

Cognee has two distinct HTTP phases for the v1 API: ``/api/v1/add`` accepts
data (as multipart form data), and ``/api/v1/cognify`` builds the graph from a
dataset.  This module deliberately keeps those phases visible in integration
status.  An HTTP 200 from ``add`` is only a submission; it is never reported as
an already constructed or queryable memory.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

import httpx

from app.models import Diagnosis, FailureType, IntegrationStatus, QueryProfile, StrategyRun

MAX_RELATIONSHIPS = 256
MAX_TEXT_LENGTH = 512
MAX_DOCUMENTS = 256


@dataclass(frozen=True)
class NativeHTTPResult:
    """A transport result that distinguishes a request from a valid response."""

    ok: bool
    attempted: bool
    detail: str
    # Most endpoints return objects; /api/v1/search is documented to return a
    # list of result objects. Endpoint code validates the shape it needs.
    data: Any = None
    status_code: int | None = None


class NativeHTTP:
    """Small HTTP client for Cognee's documented REST API.

    ``transport`` is intentionally injectable so tests can use
    :class:`httpx.MockTransport` without making a network request.
    """

    def __init__(
        self,
        base_url: str | None,
        api_key: str | None,
        *,
        auth_mode: str = "api_key",
        timeout: float = 12.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        normalized = base_url.strip().rstrip("/") if isinstance(base_url, str) else ""
        if normalized.lower().endswith("/api/v1"):
            normalized = normalized[: -len("/api/v1")]
        self.base_url = normalized or None
        self.api_key = api_key.strip() if isinstance(api_key, str) and api_key.strip() else None
        self.auth_mode = auth_mode.strip().lower() if isinstance(auth_mode, str) else "api_key"
        self.timeout = timeout
        self.transport = transport

    @property
    def configured(self) -> bool:
        # Missing credentials deliberately keep the local fallback active;
        # anonymous self-hosting must be opted into outside this adapter.
        return bool(self.base_url and self.api_key)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            if self.auth_mode == "bearer":
                headers["Authorization"] = f"Bearer {self.api_key}"
            else:
                headers["X-Api-Key"] = self.api_key
        return headers

    async def _request(
        self,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        form_payload: dict[str, str] | None = None,
        file_payload: dict[str, tuple[str, bytes, str]] | None = None,
        allow_list: bool = False,
    ) -> NativeHTTPResult:
        if not self.base_url:
            return NativeHTTPResult(
                False, False, "No Cognee endpoint configured; local fallback used."
            )
        if (json_payload is None) == (form_payload is None):
            return NativeHTTPResult(
                False, False, "Invalid Cognee request payload; local fallback used."
            )

        kwargs: dict[str, Any] = {"timeout": self.timeout}
        if self.transport is not None:
            kwargs["transport"] = self.transport
        try:
            async with httpx.AsyncClient(**kwargs) as client:
                request_kwargs: dict[str, Any] = {"headers": self._headers()}
                if form_payload is not None:
                    # Cognee's /add endpoint explicitly requires multipart form
                    # fields (not application/x-www-form-urlencoded).
                    request_kwargs["files"] = [
                        (key, (None, value)) for key, value in form_payload.items()
                    ]
                    request_kwargs["files"].extend((file_payload or {}).items())
                else:
                    request_kwargs["json"] = json_payload
                response = await client.post(f"{self.base_url}{path}", **request_kwargs)
                status_code = response.status_code
                if not response.is_success:
                    return NativeHTTPResult(
                        False,
                        True,
                        f"Cognee returned HTTP {status_code}; local fallback used.",
                        status_code=status_code,
                    )
                if not response.content:
                    return NativeHTTPResult(
                        False,
                        True,
                        "Cognee returned an empty response; local fallback used.",
                        status_code=status_code,
                    )
                payload = response.json()
        except (httpx.HTTPError, TypeError, ValueError) as error:
            return NativeHTTPResult(
                False,
                True,
                f"Cognee unavailable or returned invalid JSON ({type(error).__name__}); local fallback used.",
            )
        if not isinstance(payload, dict) and not (allow_list and isinstance(payload, list)):
            return NativeHTTPResult(
                False,
                True,
                "Cognee returned a JSON value instead of an object; local fallback used.",
                status_code=status_code,
            )
        return NativeHTTPResult(
            True, True, "Cognee returned a valid response.", payload, status_code
        )

    async def post_form(self, path: str, payload: dict[str, str]) -> NativeHTTPResult:
        return await self._request(path, form_payload=payload)

    async def add_document(self, text: str, dataset: str) -> NativeHTTPResult:
        return await self._request(
            "/api/v1/add",
            form_payload={"datasetName": dataset},
            file_payload={"data": ("retrievallab-memory.txt", text.encode("utf-8"), "text/plain")},
        )

    async def post_json(
        self, path: str, payload: dict[str, Any], *, allow_list: bool = False
    ) -> NativeHTTPResult:
        return await self._request(path, json_payload=payload, allow_list=allow_list)


def _setting(settings: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        value = getattr(settings, name, None)
        if value is not None:
            return value
    return default


def _status(
    *,
    mode: str,
    called: bool,
    detail: str,
) -> IntegrationStatus:
    return IntegrationStatus(
        name="Cognee",
        role="memory construction",
        mode=mode,
        called=called,
        detail=detail,
    )


def _safe_relationships(value: Any, *, allowed_entities: set[str]) -> list[list[str]] | None:
    if not isinstance(value, list) or len(value) > MAX_RELATIONSHIPS:
        return None
    relationships: list[list[str]] = []
    for relation in value:
        if (
            not isinstance(relation, list)
            or len(relation) != 3
            or any(
                not isinstance(part, str) or not part.strip() or len(part) > MAX_TEXT_LENGTH
                for part in relation
            )
            or relation[1] not in {"SUFFERED_FROM", "SOLVED_BY", "RETRIEVED"}
            or relation[0] not in allowed_entities
            or relation[2] not in allowed_entities
        ):
            return None
        relationships.append(list(relation))
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
        value = memory[key]
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT_LENGTH:
            return False
    try:
        FailureType(memory["failure_type"])
        # Import lazily to keep this adapter's public imports small.
        from app.models import StrategyName

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
    if "quality" in memory:
        quality = memory["quality"]
        if (
            isinstance(quality, bool)
            or not isinstance(quality, (int, float))
            or not math.isfinite(float(quality))
            or not 0 <= float(quality) <= 1
        ):
            return False
    corpus_version = memory.get("corpus_version")
    if corpus_version is not None and (
        not isinstance(corpus_version, str)
        or not corpus_version.strip()
        or len(corpus_version) > MAX_TEXT_LENGTH
    ):
        return False
    if "relationships" in memory:
        allowed = {
            memory["query_pattern"],
            memory["failure_type"],
            memory["winning_strategy"],
            *document_ids,
        }
        if _safe_relationships(memory["relationships"], allowed_entities=allowed) is None:
            return False
    return True


def _response_has_canonical_memory(value: Any, memory: dict[str, Any]) -> bool:
    """Check search output without treating arbitrary remote text as trusted data."""

    if isinstance(value, dict):
        if (
            value.get("memory_id") == memory["memory_id"]
            and value.get("query_pattern") == memory["query_pattern"]
        ):
            return True
        return any(_response_has_canonical_memory(item, memory) for item in value.values())
    if isinstance(value, list):
        return any(_response_has_canonical_memory(item, memory) for item in value)
    if isinstance(value, str):
        return memory["memory_id"] in value and memory["query_pattern"] in value
    return False


def _valid_add_response(data: Any) -> bool:
    """Validate the generated /add response before calling cognify."""

    if not isinstance(data, dict):
        return False
    status = data.get("status")
    if not isinstance(status, str) or status.strip().lower() in {
        "",
        "failed",
        "failure",
        "error",
    }:
        return False
    # The current response schema marks these identifiers as required.
    return all(
        isinstance(data.get(key), str) and data[key].strip()
        for key in ("pipeline_run_id", "dataset_id", "dataset_name")
    )


def _valid_cognify_response(data: Any) -> bool:
    """A blocking cognify may return ``{}``, but failure statuses are not success."""

    if not isinstance(data, dict) or data.get("success") is False or data.get("error"):
        return False
    failure_states = {"failed", "failure", "error", "queued", "processing", "pending", "running"}

    def has_failure_marker(value: Any) -> bool:
        if isinstance(value, dict):
            status = value.get("status")
            if isinstance(status, str) and status.strip().lower() in failure_states:
                return True
            return any(has_failure_marker(item) for item in value.values())
        if isinstance(value, list):
            return any(has_failure_marker(item) for item in value)
        return False

    return not has_failure_marker(data)


class CogneeMemoryConstructor:
    """Construct a canonical memory and optionally submit it to native Cognee."""

    def __init__(self, settings: Any, transport: httpx.AsyncBaseTransport | None = None) -> None:
        base_url = _setting(settings, "cognee_api_url")
        api_key = _setting(settings, "cognee_api_key")
        auth_mode = _setting(settings, "cognee_auth_mode", default="api_key")
        timeout = _setting(settings, "request_timeout_seconds", default=12.0)
        dataset = _setting(settings, "cognee_dataset", default="retrievallab")
        self.dataset = (
            dataset.strip() if isinstance(dataset, str) and dataset.strip() else "retrievallab"
        )
        self.remote = NativeHTTP(
            base_url,
            api_key,
            auth_mode=auth_mode,
            timeout=timeout,
            transport=transport,
        )

    async def construct(
        self,
        profile: QueryProfile,
        diagnosis: Diagnosis,
        winner: StrategyRun,
        *,
        publish: bool = True,
        corpus_version: str | None = None,
    ) -> tuple[dict[str, Any], IntegrationStatus]:
        stable_id = hashlib.sha256(profile.signature.encode("utf-8")).hexdigest()[:16]
        document_ids: list[str] = []
        for result in winner.results[:3]:
            if result.document.id not in document_ids:
                document_ids.append(result.document.id)
        memory: dict[str, Any] = {
            "memory_id": f"pattern:{stable_id}",
            "query_pattern": profile.signature,
            "failure_type": diagnosis.failure_type.value,
            "winning_strategy": winner.strategy.value,
            "useful_document_ids": document_ids,
            "quality": winner.quality_score,
            "relationships": [
                [profile.signature, "SUFFERED_FROM", diagnosis.failure_type.value],
                [profile.signature, "SOLVED_BY", winner.strategy.value],
                *[[winner.strategy.value, "RETRIEVED", item] for item in document_ids],
            ],
        }
        if isinstance(corpus_version, str) and corpus_version.strip():
            memory["corpus_version"] = corpus_version.strip()
        if not _valid_memory_payload(memory):
            # This can only happen if upstream models violate their own contract;
            # retaining the explicit status is safer than attempting an invalid call.
            return memory, _status(
                mode="local-fallback",
                called=False,
                detail="Canonical memory failed validation; Cognee was not called.",
            )
        if not publish:
            return memory, _status(
                mode="local-fallback",
                called=False,
                detail="Memory was not promoted by the quality gate; Cognee submission skipped.",
            )
        if not self.remote.configured:
            return memory, _status(
                mode="local-fallback",
                called=False,
                detail="Cognee endpoint and API key are not both configured; canonical memory constructed locally.",
            )

        # Cognee's documented /add endpoint uses multipart form fields, not a
        # made-up JSON memory construction route.  Store the canonical object as
        # text so a later search can prove the remote graph contains this identity.
        raw_memory = json.dumps(memory, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        add = await self.remote.add_document(raw_memory, self.dataset)
        if not add.ok:
            return memory, _status(mode="local-fallback", called=add.attempted, detail=add.detail)
        if not _valid_add_response(add.data):
            return memory, _status(
                mode="local-fallback",
                called=True,
                detail="Cognee /add response failed the documented acknowledgement contract; local memory retained.",
            )

        cognify = await self.remote.post_json(
            "/api/v1/cognify",
            {
                "datasets": [self.dataset],
                (
                    "runInBackground" if self.remote.auth_mode == "api_key" else "run_in_background"
                ): False,
            },
        )
        if (
            not cognify.ok
            or cognify.status_code == 202
            or not _valid_cognify_response(cognify.data)
        ):
            return memory, _status(
                mode="remote-submitted",
                called=True,
                detail=(
                    "Cognee accepted /add, but /cognify did not complete; data is submitted "
                    "and remote queryability is unconfirmed. " + cognify.detail
                ),
            )

        # /cognify blocks by default, so the graph construction itself is complete.
        # Search once to distinguish a constructed graph from one that is actually
        # queryable for this canonical memory. An empty or unrelated search is not
        # promoted to a success claim.
        search = await self.remote.post_json(
            "/api/v1/search",
            {
                "query": profile.signature,
                ("searchType" if self.remote.auth_mode == "api_key" else "search_type"): "CHUNKS",
                "datasets": [self.dataset],
                ("topK" if self.remote.auth_mode == "api_key" else "top_k"): 5,
            },
            allow_list=True,
        )
        if search.ok and _response_has_canonical_memory(search.data, memory):
            return memory, _status(
                mode="remote-queryable",
                called=True,
                detail="Cognee accepted /add, completed /cognify, and returned this memory from /search.",
            )
        return memory, _status(
            mode="remote-constructed",
            called=True,
            detail=(
                "Cognee accepted /add and completed /cognify; remote queryability was not "
                "confirmed, so the canonical local memory remains authoritative."
            ),
        )
