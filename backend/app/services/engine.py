from __future__ import annotations

import asyncio
from time import perf_counter

from app.adapters.hotdata import HotdataQueryEngine
from app.adapters.sponsors import (
    CogneeMemoryConstructor,
    HydraMemoryGraph,
    RocketRideOrchestrator,
    RotePlaybook,
)
from app.config import Settings
from app.models import (
    Diagnosis,
    IntegrationStatus,
    QualitySignals,
    QueryProfile,
    RetrievalRunRequest,
    RetrievalRunResponse,
    RunOutcome,
    SearchResult,
    StrategyName,
    StrategyRun,
)
from app.services.analyzer import diagnose
from app.services.query import understand_query
from app.services.security import redact_sensitive, safe_evidence_text
from app.services.state import StateRepository
from app.services.text import tokenize


class RetrievalEngine:
    def __init__(
        self,
        settings: Settings,
        state: StateRepository,
        hotdata: HotdataQueryEngine,
        rocketride: RocketRideOrchestrator,
        cognee: CogneeMemoryConstructor,
        hydra: HydraMemoryGraph,
        rote: RotePlaybook,
    ):
        self.settings = settings
        self.state = state
        self.hotdata = hotdata
        self.rocketride = rocketride
        self.cognee = cognee
        self.hydra = hydra
        self.rote = rote
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_runs)

    async def run(self, request: RetrievalRunRequest) -> RetrievalRunResponse:
        async with self._semaphore:
            return await self._run(request)

    async def _run(self, request: RetrievalRunRequest) -> RetrievalRunResponse:
        started = perf_counter()
        profile = understand_query(request.query)
        trace = [f"classified:{profile.query_type}"]
        integrations: list[IntegrationStatus] = []

        memory, hydra_read = await self.hydra.find_play(profile)
        integrations.append(hydra_read)
        trace.append("hydra:memory_hit" if memory else "hydra:memory_miss")

        play = None
        if memory and not request.force_discovery:
            play, rote_read = await self.rote.recall(profile.signature)
            integrations.append(rote_read)

        baseline_skipped = False
        replay_attempted = bool(memory and play and not request.force_discovery)
        if replay_attempted:
            path = "replay"
            planner_calls = 0
            # Looking up a local play must never execute external code. Only an
            # explicitly configured, reviewed native Play is invoked at replay.
            rocket_status = await self.rocketride.execute_play(profile, play)
            integrations.append(rocket_status)
            replay_run, hot_status, rote_status = await self.rote.replay_retrieval(
                profile, play["strategy"], request.top_k
            )
            integrations.append(rote_status)
            if replay_run is None:
                replay_run, hot_status = await self._execute(profile, play["strategy"], request.top_k)
            integrations.append(hot_status)
            # Rote recall is read-only; count a replay only after retrieval executed.
            self.state.record_replay(profile.signature)
            winner = replay_run
            baseline = replay_run
            baseline_skipped = True
            diagnosis = Diagnosis(
                failure_type=memory.failure_type,
                confidence=memory.similarity,
                explanation=(
                    "The memory adapter recognized a previously solved query pattern, so "
                    "the baseline diagnostic search was skipped and its saved strategy was "
                    "replayed. Provider statuses show which stages ran natively or locally."
                ),
                signals=replay_run.signals,
            )
            experiments = [replay_run]
            trace.extend([
                "baseline:skipped",
                f"analyzer:recalled:{memory.failure_type.value}",
                f"rote:replay:v{play['version']}",
                f"winner:{winner.strategy.value}",
            ])
            if not self._valid_retrieval(profile, replay_run):
                trace.append("rote:replay_failed_quality_gate")
                path = "discovery"
                planner_calls = 1
                baseline_skipped = False
                discovery_baseline, diagnosis, discovered_experiments, winner = await self._discover(
                    profile, request.top_k, integrations, trace
                )
                baseline = discovery_baseline
                # Preserve the failed replay attempt for honest retrieval accounting.
                experiments = [replay_run, *discovered_experiments]
        else:
            path = "discovery"
            planner_calls = 1
            baseline, diagnosis, experiments, winner = await self._discover(
                profile, request.top_k, integrations, trace
            )

        successful = self._valid_retrieval(profile, winner)
        outcome = RunOutcome.SUCCESS if successful else RunOutcome.DEGRADED
        quality_lift = None if baseline_skipped else round(
            winner.quality_score - baseline.quality_score, 4
        )
        meaningful_lift = successful and (
            diagnosis.failure_type.value == "none"
            or (quality_lift is not None and quality_lift >= 0.02)
        )
        # Replays validate the remembered play but do not re-promote the same memory.
        promoted = bool(path == "discovery" and meaningful_lift)
        answer = self._grounded_answer(profile, winner)
        memory_delta, cognee_status = await self.cognee.construct(
            profile, diagnosis, winner,
            publish=promoted, corpus_version=self.state.corpus_version,
        )
        integrations.append(cognee_status)
        memory_delta.setdefault("corpus_version", self.state.corpus_version)
        hydra_write = await self.hydra.write(memory_delta, promoted=promoted)
        integrations.append(hydra_write)
        if promoted and hydra_write.mode == "error-fallback":
            promoted = False
            trace.append("memory:promotion_failed")
        play_captured = False
        if path == "discovery" and promoted:
            rote_capture = await self.rote.capture(profile.signature, winner)
            integrations.append(rote_capture)
            play_captured = rote_capture.mode != "error-fallback"
            trace.append("play:captured_local" if play_captured else "play:capture_failed")

        elapsed_ms = round((perf_counter() - started) * 1000, 2)
        response = RetrievalRunResponse(
            query=request.query,
            query_profile=profile,
            path=path,
            memory_match=memory,
            baseline=baseline,
            baseline_skipped=baseline_skipped,
            diagnosis=diagnosis,
            experiments=experiments,
            winner=winner,
            answer=answer,
            evidence=self._answer_results(profile, winner)[:3],
            planner_calls=planner_calls,
            retrieval_attempts=len(experiments),
            elapsed_ms=elapsed_ms,
            integrations=integrations,
            trace=trace,
            outcome=outcome,
            memory_promoted=promoted,
            play_captured=play_captured,
            replay_attempted=replay_attempted,
            quality_lift=quality_lift,
            demo_mode=self.settings.demo_mode,
        )
        state_payload = {
            "run_id": response.run_id,
            "query": redact_sensitive(request.query),
            "query_pattern": profile.signature,
            "path": path,
            "strategy": winner.strategy.value,
            "quality": winner.quality_score,
            "attempts": len(experiments),
            "planner_calls": planner_calls,
            "elapsed_ms": elapsed_ms,
            "outcome": outcome.value,
            "baseline_quality": None if baseline_skipped else baseline.quality_score,
            "quality_lift": quality_lift,
            "memory_promoted": promoted,
            "play_captured": play_captured,
            "replay_attempted": replay_attempted,
            "memory_hit": memory is not None,
            "corpus_version": self.state.corpus_version,
            "created_at": response.created_at.isoformat(),
        }
        self.state.save_run(state_payload)
        telemetry_payload = {
            **state_payload,
            # Make the metric scope explicit: telemetry receives the measured run
            # duration available before this outbound call.
            "elapsed_scope": "before_telemetry",
        }
        telemetry_status = await self.hotdata.record_telemetry(telemetry_payload)
        elapsed_ms = round((perf_counter() - started) * 1000, 2)
        response.elapsed_ms = elapsed_ms
        state_payload["elapsed_ms"] = elapsed_ms
        # Persist the final API-visible duration, including telemetry. This second
        # upsert is idempotent and keeps dashboard savings truthful.
        self.state.save_run(state_payload)
        response.integrations.append(telemetry_status)
        response.trace.extend([
            f"cognee:{cognee_status.mode}",
            "hydra:promoted" if promoted else "hydra:run_only",
            "telemetry:recorded",
            f"outcome:{outcome.value}",
        ])
        return response

    async def _discover(
        self,
        profile: QueryProfile,
        top_k: int,
        integrations: list[IntegrationStatus],
        trace: list[str],
    ) -> tuple[StrategyRun, Diagnosis, list[StrategyRun], StrategyRun]:
        baseline, baseline_status = await self._execute(profile, StrategyName.DENSE, top_k)
        integrations.append(baseline_status)
        diagnosis = diagnose(profile, baseline.results)
        trace.append(f"analyzer:{diagnosis.failure_type.value}")
        strategies, rocket_status = await self.rocketride.plan(profile, diagnosis)
        integrations.append(rocket_status)
        repair_strategies = [item for item in strategies if item is not StrategyName.DENSE]
        trace.append(f"rocketride:plan:{','.join(item.value for item in strategies)}")
        executions = await asyncio.gather(
            *(self._execute(profile, strategy, top_k) for strategy in repair_strategies)
        )
        experiments = [baseline, *(item[0] for item in executions)]
        integrations.extend(item[1] for item in executions)
        valid_experiments = [item for item in experiments if self._valid_retrieval(profile, item)]
        winner_pool = valid_experiments or experiments
        winner = max(winner_pool, key=lambda item: (item.quality_score, -item.latency_ms))
        trace.append(f"winner:{winner.strategy.value}")
        return baseline, diagnosis, experiments, winner

    async def _execute(
        self, profile: QueryProfile, strategy: StrategyName, top_k: int
    ) -> tuple[StrategyRun, IntegrationStatus]:
        """Execute one retrieval while preserving a failed attempt as an observation."""
        started = perf_counter()
        try:
            return await self.hotdata.execute(profile, strategy, top_k)
        except Exception as error:  # noqa: BLE001 - adapter failures become run observations
            run = StrategyRun(
                strategy=strategy,
                results=[],
                quality_score=0,
                latency_ms=round((perf_counter() - started) * 1000, 2),
                signals=QualitySignals(
                    exact_token_recall=0,
                    semantic_relevance=0,
                    evidence_coverage=0,
                    diversity=0,
                    metadata_match=0,
                    freshness=0,
                ),
            )
            return run, IntegrationStatus(
                name="hotdata.dev",
                role=f"live {strategy.value} query",
                mode="error-fallback",
                called=True,
                detail=f"Retrieval failed; recorded degraded attempt ({type(error).__name__})",
            )

    @staticmethod
    def _valid_retrieval(profile: QueryProfile, run: StrategyRun) -> bool:
        if not run.results:
            return False
        if run.quality_score < 0.55:
            return False
        if profile.exact_identifiers and (
            run.signals.exact_token_recall < 0.5
            or not RetrievalEngine._all_identifiers_present(profile, run)
        ):
            return False
        if profile.current_intent:
            top = run.results[0].document
            top_tags = {tag.lower() for tag in top.tags}
            top_text = " ".join([top.title, top.content, *top.tags]).lower()
            if "archived" in top_tags or "superseded" in top_text:
                return False
        if profile.current_intent and run.signals.freshness < 0.72:
            return False
        return bool(RetrievalEngine._eligible_results(profile, run))

    @staticmethod
    def _all_identifiers_present(profile: QueryProfile, run: StrategyRun) -> bool:
        token_sets = [
            set(tokenize(" ".join([
                result.document.id, result.document.title, result.document.content, *result.document.tags
            ]), remove_stop_words=False))
            for result in run.results
        ]
        return all(
            any(identifier.lower() in tokens for tokens in token_sets)
            for identifier in profile.exact_identifiers
        )

    @staticmethod
    def _eligible_results(profile: QueryProfile, run: StrategyRun) -> list[SearchResult]:
        """Return only evidence that can support this query's answer.

        Retrieval rank alone is not an answer-grounding contract. In particular, a
        current billing question must not quote a newer authentication incident, and
        an archived/superseded policy is never eligible merely because it was retrieved.
        """
        eligible = []
        for result in run.results:
            document = result.document
            tags = {tag.lower() for tag in document.tags}
            text = " ".join([document.id, document.title, document.content, *document.tags]).lower()
            if profile.exact_identifiers and not any(
                identifier.lower() in tokenize(text, remove_stop_words=False)
                for identifier in profile.exact_identifiers
            ):
                continue
            if profile.current_intent:
                if "archived" in tags or "superseded" in text:
                    continue
                # Domain is a hard boundary for current policy/incident answers.
                if document.product.lower() != profile.domain.lower() and profile.domain.lower() not in text:
                    continue
                if not any(term in text for term in profile.terms if term not in {"current", "latest", "newest", "today", "now", "effective"}):
                    continue
            elif not profile.exact_identifiers and not any(
                term in text for term in profile.terms
            ):
                continue
            eligible.append(result)
        if profile.current_intent and eligible:
            newest = max(item.document.published_at for item in eligible)
            eligible = [item for item in eligible if item.document.published_at == newest]
        return sorted(eligible, key=lambda item: item.rank)

    @staticmethod
    def _answer_results(profile: QueryProfile, run: StrategyRun) -> list[SearchResult]:
        eligible = RetrievalEngine._eligible_results(profile, run)
        if not profile.exact_identifiers:
            return eligible
        # A multi-ID request must cite a source for every requested identifier;
        # returning only the first matching incident would be a partial answer.
        selected: list[SearchResult] = []
        for identifier in profile.exact_identifiers:
            matches = [
                item for item in eligible
                if identifier.lower() in tokenize(
                    " ".join([
                        item.document.id, item.document.title, item.document.content, *item.document.tags
                    ]), remove_stop_words=False
                )
            ]
            if not matches:
                return []
            if matches[0] not in selected:
                selected.append(matches[0])
        return selected

    @staticmethod
    def _grounded_answer(profile: QueryProfile, winner: StrategyRun) -> str:
        if not RetrievalEngine._valid_retrieval(profile, winner):
            return "I could not find enough reliable evidence to answer this query."
        eligible = RetrievalEngine._answer_results(profile, winner)
        if not eligible:
            return "I could not find enough reliable evidence to answer this query."
        passages: list[str] = []
        for source in eligible:
            safe_text, was_suspicious = safe_evidence_text(source.document.content)
            sentences = [part.strip() for part in safe_text.split(".") if part.strip()][:4]
            if not sentences:
                continue
            suffix = " [untrusted instructions filtered]" if was_suspicious else ""
            passage = ". ".join(sentences) + "."
            passages.append(f"{passage} ({source.document.title}){suffix}")
        if not passages:
            return "I could not find enough reliable evidence to answer this query."
        return "Based on the highest-quality retrieved evidence: " + " ".join(passages)
