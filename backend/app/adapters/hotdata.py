from __future__ import annotations

import math
from datetime import UTC
from time import perf_counter
from typing import Any

from app.adapters.sponsors import RemoteBridge, _acknowledged, _status
from app.config import Settings
from app.models import IntegrationStatus, QueryProfile, SearchResult, StrategyName, StrategyRun
from app.services.analyzer import calculate_signals, quality_score
from app.services.retrieval import Corpus
from app.services.security import redact_sensitive

MAX_TOP_K = 10
MAX_REMOTE_RESULTS = 10


def _normalize_remote_results(
    values: Any, strategy: StrategyName, top_k: int
) -> list[SearchResult] | None:
    """Validate result records and normalize rank/date before analyzer use.

    Remote rank is never trusted as an index into the result list. Scores are
    constrained to finite normalized values, and document timestamps must carry
    timezone information so freshness arithmetic cannot be poisoned by naive dates.
    """

    if not isinstance(values, list):
        return None
    if not values:
        # An explicit remote empty result is meaningful and must not silently turn
        # into a local success.
        return []
    normalized: list[SearchResult] = []
    for item in values[: min(top_k, MAX_REMOTE_RESULTS)]:
        if not isinstance(item, dict):
            return None
        raw_score = item.get("score")
        if (
            isinstance(raw_score, bool)
            or not isinstance(raw_score, (int, float))
            or not math.isfinite(float(raw_score))
            or not 0 <= float(raw_score) <= 1
        ):
            return None
        raw_rank = item.get("rank")
        if (
            isinstance(raw_rank, bool)
            or not isinstance(raw_rank, int)
            or not 1 <= raw_rank <= 1_000_000
        ):
            return None
        reasons = item.get("reasons", [])
        if not isinstance(reasons, list) or any(not isinstance(reason, str) for reason in reasons):
            return None
        try:
            # Force the strategy at the adapter boundary; a bridge cannot relabel
            # results as a different strategy and affect downstream comparisons.
            result = SearchResult.model_validate({**item, "strategy": strategy.value})
        except (TypeError, ValueError):
            return None
        if result.strategy is not strategy:
            return None
        published_at = result.document.published_at
        try:
            offset = published_at.utcoffset()
        except (OverflowError, ValueError):
            return None
        if published_at.tzinfo is None or offset is None:
            return None
        normalized_document = result.document.model_copy(
            update={"published_at": published_at.astimezone(UTC)}
        )
        normalized.append(
            result.model_copy(update={"document": normalized_document, "rank": raw_rank})
        )

    # Rank by validated quality and then normalize ranks. The bridge's rank field
    # is treated as untrusted metadata rather than a positional instruction.
    normalized.sort(
        key=lambda result: (
            -result.score,
            -result.document.published_at.timestamp(),
            result.document.id,
        )
    )
    return [result.model_copy(update={"rank": index}) for index, result in enumerate(normalized, 1)]


class HotdataQueryEngine:
    def __init__(self, settings: Settings, corpus: Corpus):
        self.corpus = corpus
        self.remote = RemoteBridge(
            settings.hotdata_base_url, settings.hotdata_api_key, settings.request_timeout_seconds
        )

    async def execute(
        self, profile: QueryProfile, strategy: StrategyName, top_k: int
    ) -> tuple[StrategyRun, IntegrationStatus]:
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= MAX_TOP_K:
            raise ValueError(f"top_k must be an integer between 1 and {MAX_TOP_K}")
        started = perf_counter()
        remote = await self.remote.post(
            "/v1/query",
            {
                "query": redact_sensitive(profile.raw_query),
                "strategy": strategy.value,
                "top_k": top_k,
                "workload": "retrieval_candidates",
            },
        )
        # The local engine remains the development fallback until a deployment-
        # specific bridge is verified. A valid remote empty list is still a valid
        # result and must be used as-is.
        results: list[SearchResult] | None = None
        accepted_remote_results = False
        if remote.called and isinstance(remote.data, dict) and "results" in remote.data:
            mapped = _normalize_remote_results(remote.data["results"], strategy, top_k)
            if mapped is not None:
                results = mapped
                accepted_remote_results = True
        if results is None:
            try:
                results = self.corpus.search(profile, strategy, top_k)
            except (ValueError, ZeroDivisionError):
                # A verified remote response can still serve an empty corpus. If
                # neither side can produce candidates, preserve a truthful empty
                # run instead of turning a local fallback into a server error.
                results = []
        signals = calculate_signals(profile, results)
        run = StrategyRun(
            strategy=strategy,
            results=results,
            quality_score=quality_score(profile, signals),
            latency_ms=round((perf_counter() - started) * 1000, 2),
            signals=signals,
        )
        status = _status(
            "hotdata.dev",
            f"live {strategy.value} query",
            remote,
            accepted=accepted_remote_results,
            remote_mode="remote+normalized-local",
            fallback_detail="Executed the retrieval strategy against the local corpus; remote results were absent or failed validation.",
        )
        return run, status

    async def record_telemetry(self, payload: dict) -> IntegrationStatus:
        remote = await self.remote.post("/v1/query/telemetry", payload)
        return _status(
            "hotdata.dev",
            "live retrieval telemetry",
            remote,
            accepted=_acknowledged(remote.data),
            remote_mode="remote",
            fallback_detail="Telemetry retained in the local run store; remote recording was not acknowledged.",
        )
