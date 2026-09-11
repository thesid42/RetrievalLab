"""Native RocketRide pipeline integration.

RocketRide is a WebSocket pipeline runtime, not an HTTP REST bridge.  This
adapter deliberately keeps the SDK import lazy so the application can run
with its local retrieval implementation when the optional ``rocketride``
package, a pipeline, or a runtime endpoint is not configured.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Protocol

from app.models import (
    Diagnosis,
    FailureType,
    IntegrationStatus,
    QueryProfile,
    StrategyName,
)
from app.services.security import redact_sensitive

MAX_PLAN_STRATEGIES = 5
MAX_PLAY_STEPS = 32
MAX_RESULT_DEPTH = 4


class RocketRideClientLike(Protocol):
    async def use(self, **kwargs: Any) -> Mapping[str, Any]: ...

    async def send(
        self,
        token: str,
        data: str | bytes,
        objinfo: dict[str, Any] | None = None,
        mimetype: str | None = None,
    ) -> Any: ...

    async def terminate(self, token: str) -> Any: ...


ClientFactory = Callable[[str, str, float], RocketRideClientLike]


def _default_client_factory(uri: str, api_key: str, timeout_seconds: float) -> RocketRideClientLike:
    """Create the official client without importing the optional package eagerly."""

    try:
        from rocketride import RocketRideClient  # type: ignore[import-not-found]
    except ImportError as error:  # pragma: no cover - depends on installation
        raise RuntimeError("rocketride package is not installed") from error
    # The SDK's request_timeout is documented in milliseconds.  The app setting
    # is intentionally kept in seconds to match the rest of the API.
    return RocketRideClient(
        uri=uri,
        auth=api_key,
        request_timeout=timeout_seconds * 1000,
    )


@asynccontextmanager
async def _client_context(client: RocketRideClientLike) -> AsyncIterator[RocketRideClientLike]:
    """Support the SDK async context manager and small test doubles alike."""

    enter = getattr(client, "__aenter__", None)
    exit_ = getattr(client, "__aexit__", None)
    if enter is not None and exit_ is not None:
        async with client as connected:
            yield connected
        return

    connect = getattr(client, "connect", None)
    disconnect = getattr(client, "disconnect", None)
    if connect is not None:
        await connect()
    try:
        yield client
    finally:
        if disconnect is not None:
            await disconnect()


def _setting(settings: Any, name: str, default: Any = None) -> Any:
    """Read settings without coupling this adapter to a particular Settings model."""

    value = getattr(settings, name, default)
    return value if value not in ("", None) else default


def _base_strategies(diagnosis: Diagnosis) -> list[StrategyName]:
    if diagnosis.failure_type is FailureType.LEXICAL:
        return [StrategyName.BM25, StrategyName.HYBRID, StrategyName.HYBRID_RERANK]
    if diagnosis.failure_type is FailureType.STALE:
        return [StrategyName.HYBRID, StrategyName.FRESHNESS, StrategyName.HYBRID_RERANK]
    if diagnosis.failure_type is FailureType.NONE:
        return [StrategyName.DENSE]
    return [StrategyName.BM25, StrategyName.HYBRID, StrategyName.HYBRID_RERANK]


def _safe_profile_payload(profile: QueryProfile) -> dict[str, Any]:
    payload = profile.model_dump(mode="json")
    # Every field in QueryProfile is derived from the user's raw query.  It is
    # not sufficient to redact only ``raw_query``: identifiers can be copied
    # into signatures/domains and terms can carry credentials verbatim.
    for field in ("raw_query", "normalized_query", "query_type", "signature", "domain"):
        payload[field] = redact_sensitive(str(payload.get(field, "")))
    payload["exact_identifiers"] = [
        redact_sensitive(value) for value in profile.exact_identifiers
    ]
    payload["terms"] = [redact_sensitive(value) for value in profile.terms]
    return payload


def _valid_play(play: Any, signature: str) -> dict[str, Any] | None:
    """Validate the local play contract before it crosses a native boundary."""

    if not isinstance(play, dict):
        return None
    if play.get("query_pattern") != signature:
        return None
    try:
        strategy = play.get("strategy")
        strategy = strategy if isinstance(strategy, StrategyName) else StrategyName(strategy)
    except (TypeError, ValueError):
        return None
    version = play.get("version")
    steps = play.get("steps")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version < 1
        or not isinstance(steps, list)
        or not steps
        or len(steps) > MAX_PLAY_STEPS
        or any(not isinstance(step, str) or not step.strip() for step in steps)
    ):
        return None
    return {
        "query_pattern": signature,
        "strategy": strategy,
        "version": version,
        "steps": [step.strip() for step in steps],
    }


def _mapping_candidates(value: Any, depth: int = 0) -> list[Mapping[str, Any]]:
    """Bounded traversal of the SDK's dynamic pipeline result envelope."""

    if depth > MAX_RESULT_DEPTH:
        return []
    if isinstance(value, Mapping):
        result = [value]
        # PIPELINE_RESULT exposes dynamic fields described by ``result_types``.
        # In practice those fields are commonly named text/answers/output, but
        # a .pipe can choose any field name.  Include the documented envelope
        # keys plus the dynamic field names while keeping traversal bounded.
        keys: list[str] = [
            "result",
            "body",
            "data",
            "output",
            "payload",
            "value",
            "text",
            "answers",
            "content",
        ]
        result_types = value.get("result_types")
        if isinstance(result_types, Mapping):
            keys.extend(
                key for key in result_types if isinstance(key, str) and key not in keys
            )
        for key in keys:
            if key in value:
                result.extend(_mapping_candidates(value[key], depth + 1))
        return result
    if isinstance(value, list):
        result: list[Mapping[str, Any]] = []
        for item in value[:32]:
            result.extend(_mapping_candidates(item, depth + 1))
        return result
    if isinstance(value, str) and len(value) <= 100_000:
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return _mapping_candidates(decoded, depth + 1)
    return []


def _remote_strategies(value: Any, allowed: set[str]) -> list[StrategyName] | None:
    for candidate in _mapping_candidates(value):
        raw = candidate.get("strategies")
        if not isinstance(raw, list):
            continue
        proposed: list[StrategyName] = []
        seen: set[str] = set()
        for item in raw[:MAX_PLAN_STRATEGIES]:
            if not isinstance(item, str) or item not in allowed or item in seen:
                continue
            seen.add(item)
            proposed.append(StrategyName(item))
        if proposed:
            return proposed
    return None


def _status(
    *,
    mode: str,
    called: bool,
    detail: str,
    role: str = "native pipeline orchestration",
) -> IntegrationStatus:
    return IntegrationStatus(
        name="RocketRide",
        role=role,
        mode=mode,
        called=called,
        detail=detail,
    )


class RocketRideOrchestrator:
    """Use a configured RocketRide ``.pipe`` while preserving local semantics."""

    def __init__(self, settings: Any, client_factory: ClientFactory | None = None):
        self.uri = _setting(settings, "rocketride_uri")
        self.api_key = _setting(settings, "rocketride_api_key", "")
        self.pipeline_path = _setting(settings, "rocketride_pipeline_path")
        self.source_id = _setting(settings, "rocketride_source_id")
        self.timeout_seconds = float(
            _setting(settings, "request_timeout_seconds", 12.0)
        )
        self.client_factory = client_factory or _default_client_factory

    @property
    def native_configured(self) -> bool:
        return bool(self.uri and self.api_key and self.pipeline_path and self.source_id)

    def _local_status(self, detail: str) -> IntegrationStatus:
        return _status(
            mode="local-fallback",
            called=False,
            detail=detail,
            role="advisor and tool orchestration",
        )

    async def _dispatch(self, payload: dict[str, Any]) -> Any:
        if not self.uri:
            raise RuntimeError("RocketRide URI is not configured")
        pipeline = Path(self.pipeline_path) if self.pipeline_path else None
        if pipeline is None:
            raise RuntimeError("RocketRide pipeline path is not configured")
        if not pipeline.is_file():
            raise FileNotFoundError(f"RocketRide pipeline does not exist: {pipeline}")

        client = self.client_factory(str(self.uri), str(self.api_key or ""), self.timeout_seconds)

        async def invoke() -> Any:
            async with _client_context(client) as connected:
                use_kwargs: dict[str, Any] = {"filepath": str(pipeline)}
                if self.source_id:
                    use_kwargs["source"] = str(self.source_id)
                started = await connected.use(**use_kwargs)
                token = started.get("token") if isinstance(started, Mapping) else None
                if not isinstance(token, str) or not token:
                    raise RuntimeError("RocketRide use() returned no task token")
                try:
                    return await connected.send(
                        token,
                        json.dumps(payload, separators=(",", ":")),
                        objinfo={"name": "retrievallab.json"},
                        mimetype="application/json",
                    )
                finally:
                    await connected.terminate(token)

        return await asyncio.wait_for(invoke(), timeout=self.timeout_seconds)

    async def plan(
        self, profile: QueryProfile, diagnosis: Diagnosis
    ) -> tuple[list[StrategyName], IntegrationStatus]:
        strategies = _base_strategies(diagnosis)
        if not self.native_configured:
            return strategies, self._local_status(
                "RocketRide native settings are incomplete (URI, API key, .pipe path, and source are required); using the registered local-tool plan."
            )
        payload = {
            "operation": "plan",
            "query": redact_sensitive(profile.raw_query),
            "profile": _safe_profile_payload(profile),
            "diagnosis": diagnosis.model_dump(mode="json"),
            "registered_tools": [item.value for item in strategies],
        }
        try:
            output = await self._dispatch(payload)
        except (Exception, asyncio.CancelledError) as error:
            if isinstance(error, asyncio.CancelledError):
                raise
            return strategies, _status(
                mode="local-fallback",
                called=True,
                detail=(
                    "RocketRide native plan failed; using the registered local-tool plan "
                    f"({type(error).__name__})."
                ),
                role="advisor and tool orchestration",
            )
        proposed = _remote_strategies(output, {item.value for item in strategies})
        if proposed:
            return proposed, _status(
                mode="native",
                called=True,
                detail="RocketRide returned a validated plan from the configured .pipe pipeline.",
                role="advisor and tool orchestration",
            )
        return strategies, _status(
            mode="native+local-fallback",
            called=True,
            detail=(
                "RocketRide pipeline completed without a validated strategy list; "
                "using the registered local-tool plan."
            ),
            role="advisor and tool orchestration",
        )

    async def execute_play(self, profile: QueryProfile, play: dict[str, Any]) -> IntegrationStatus:
        normalized_play = _valid_play(play, profile.signature)
        if normalized_play is None:
            return _status(
                mode="local-fallback",
                called=False,
                detail="Rejected invalid play before native dispatch; local hotdata execution remains authoritative.",
                role="deterministic play execution",
            )
        if not self.native_configured:
            return _status(
                mode="local-fallback",
                called=False,
                detail=(
                    "RocketRide native settings are incomplete (URI, API key, .pipe path, and source are required); "
                    "local hotdata execution remains authoritative."
                ),
                role="deterministic play execution",
            )
        payload = {
            "operation": "execute_play",
            "query": redact_sensitive(profile.raw_query),
            "profile": _safe_profile_payload(profile),
            "play": {
                **normalized_play,
                "strategy": normalized_play["strategy"].value,
            },
        }
        try:
            await self._dispatch(payload)
        except (Exception, asyncio.CancelledError) as error:
            if isinstance(error, asyncio.CancelledError):
                raise
            return _status(
                mode="local-fallback",
                called=True,
                detail=(
                    "RocketRide native play dispatch failed; local hotdata execution "
                    f"remains authoritative ({type(error).__name__})."
                ),
                role="deterministic play execution",
            )
        return _status(
            mode="native+local-execution",
            called=True,
            detail=(
                "RocketRide accepted the play through the configured .pipe; local hotdata "
                "execution remains authoritative, and remote tool-step completion was not inferred."
            ),
            role="deterministic play execution",
        )


__all__ = ["RocketRideOrchestrator"]
