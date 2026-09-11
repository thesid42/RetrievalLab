import type { DashboardData, RetrievalRun } from "./types.ts";

export type BackendResult = {
  document: { id: string; title: string; content: string; version?: string; document_type: string; published_at: string };
  score: number;
  rank: number;
};

export type BackendStrategy = {
  strategy: string;
  quality_score: number;
  latency_ms: number;
  results: BackendResult[];
};

export type BackendRun = {
  run_id: string;
  query: string;
  query_profile: { query_type: string };
  path: string;
  memory_match?: { query_pattern: string; similarity: number; winning_strategy: string } | null;
  baseline: BackendStrategy;
  baseline_skipped: boolean;
  diagnosis: {
    failure_type: string;
    explanation: string;
    signals: Record<string, number>;
  };
  experiments: BackendStrategy[];
  winner: BackendStrategy;
  answer: string;
  evidence: BackendResult[];
  planner_calls: number;
  retrieval_attempts: number;
  elapsed_ms: number;
  trace: string[];
  integrations: Array<{ name: string; role: string; mode: string; called: boolean; detail: string }>;
  outcome?: "success" | "degraded";
  memory_promoted?: boolean;
  play_captured?: boolean;
  replay_attempted?: boolean;
  quality_lift?: number | null;
  demo_mode?: boolean;
};

export type BackendDashboard = {
  total_runs?: number;
  discovery_runs?: number;
  replay_runs?: number;
  patterns_learned?: number;
  memory_hit_rate?: number;
  average_attempts_discovery?: number;
  average_attempts_replay?: number;
  average_quality_lift?: number | null;
  attempts_saved_percent?: number | null;
  latency_saved_percent?: number | null;
  quality_history?: Array<{ id: string; quality: number; baseline_quality?: number | null; created_at: string }>;
  recent_runs?: Array<{ query: string; path: string; strategy: string; outcome?: "success" | "degraded"; memory_promoted?: boolean }>;
};

const labels: Record<string, string> = {
  dense: "Dense",
  bm25: "BM25",
  hybrid: "Hybrid",
  hybrid_rerank: "Hybrid + Rerank",
  freshness: "Freshness Weighted",
};

function displayDocument(result: BackendResult, matched = false) {
  return {
    rank: result.rank,
    title: result.document.title,
    excerpt: `${result.document.content.slice(0, 145)}${result.document.content.length > 145 ? "…" : ""}`,
    score: result.score,
    metadata: `${result.document.document_type} · ${result.document.version ?? new Date(result.document.published_at).getFullYear()}`,
    matched,
  };
}

export function normalizeRun(raw: BackendRun): RetrievalRun {
  const metricMap = [
    ["exact_token_recall", "exactTokenRecall", "Exact-token recall"],
    ["semantic_relevance", "semanticRelevance", "Semantic relevance"],
    ["evidence_coverage", "coverage", "Evidence coverage"],
    ["diversity", "diversity", "Result diversity"],
    ["metadata_match", "metadataMatch", "Metadata match"],
    ["freshness", "freshness", "Freshness"],
  ] as const;
  const winnerIndex = raw.experiments.findIndex((item) => item.strategy === raw.winner.strategy
    && item.quality_score === raw.winner.quality_score
    && item.latency_ms === raw.winner.latency_ms
    && item.results.map((result) => result.document.id).join("|") === raw.winner.results.map((result) => result.document.id).join("|"));
  const resolvedWinnerIndex = winnerIndex >= 0 ? winnerIndex : raw.experiments.findIndex((item) => item.strategy === raw.winner.strategy);
  return {
    id: raw.run_id,
    query: raw.query,
    queryType: raw.query_profile.query_type,
    status: raw.outcome ?? (raw.winner.quality_score >= 0.55 ? "success" : "degraded"),
    diagnosis: raw.diagnosis.failure_type,
    diagnosisDetail: raw.diagnosis.explanation,
    baseline: raw.baseline.results.map((item) => displayDocument(
      item,
      raw.evidence.some((evidence) => evidence.document.id === item.document.id),
    )),
    baselineSkipped: raw.baseline_skipped,
    analyzer: metricMap.map(([source, key, label]) => ({
      key,
      label,
      score: Math.round((raw.diagnosis.signals?.[source] ?? 0) * 100),
    })),
    strategies: raw.experiments.map((item, index) => ({
      name: labels[item.strategy] ?? item.strategy,
      score: Math.round(item.quality_score * 100),
      latencyMs: Math.round(item.latency_ms),
      candidates: item.results.length,
      winner: index === resolvedWinnerIndex,
    })),
    memory: {
      hit: Boolean(raw.memory_match),
      pattern: raw.memory_match?.query_pattern ?? raw.query_profile.query_type,
      similarity: raw.memory_match ? Math.round(raw.memory_match.similarity * 100) : undefined,
      play: labels[raw.winner.strategy] ?? raw.winner.strategy,
      stored: raw.memory_promoted ?? raw.trace.includes("hydra:promoted"),
      playCaptured: raw.play_captured ?? raw.trace.includes("rote:captured"),
      replayAttempted: raw.replay_attempted ?? raw.path === "replay",
    },
    answer: raw.answer,
    citations: raw.evidence.map((item) => item.document.title),
    metrics: {
      latencyMs: Math.round(raw.elapsed_ms),
      plannerCalls: raw.planner_calls,
      retrievalAttempts: raw.retrieval_attempts,
      tokens: 0,
    },
    qualityLift: Object.prototype.hasOwnProperty.call(raw, "quality_lift")
      ? raw.quality_lift == null ? null : Math.round(raw.quality_lift * 100)
      : raw.baseline_skipped ? null : Math.round((raw.winner.quality_score - raw.baseline.quality_score) * 100),
    backendDemoMode: raw.demo_mode ?? false,
    learned: raw.trace.filter((event) => /cognee|hydra|rote/.test(event)),
    providers: raw.integrations,
  };
}

export function normalizeDashboard(raw: BackendDashboard): DashboardData {
  const attemptReduction = raw.average_attempts_discovery && raw.average_attempts_replay !== undefined
    ? Math.max(0, 1 - raw.average_attempts_replay / raw.average_attempts_discovery)
    : 0;
  return {
    totalRuns: raw.total_runs ?? 0,
    memoryHitRate: Math.round((raw.memory_hit_rate ?? 0) * 100),
    qualityLift: raw.average_quality_lift == null ? null : Math.round(raw.average_quality_lift * 100),
    attemptsSaved: Object.prototype.hasOwnProperty.call(raw, "attempts_saved_percent")
      ? raw.attempts_saved_percent == null ? null : Math.round(raw.attempts_saved_percent)
      : raw.average_attempts_discovery && raw.average_attempts_replay && raw.average_attempts_replay > 0 ? Math.round(attemptReduction * 100) : null,
    latencySaved: raw.latency_saved_percent == null ? null : Math.round(raw.latency_saved_percent),
    patternsLearned: raw.patterns_learned ?? 0,
    qualityHistory: (raw.quality_history ?? []).map((item) => ({
      id: item.id,
      quality: item.quality,
      baselineQuality: item.baseline_quality ?? null,
      createdAt: item.created_at,
    })),
    recentRuns: (raw.recent_runs ?? []).map((item) => ({
      query: item.query,
      diagnosis: item.path === "replay" ? "known_pattern" : item.outcome === "degraded" ? "degraded_run" : "new_pattern",
      strategy: labels[item.strategy] ?? item.strategy,
      memoryHit: item.path === "replay",
      outcome: item.outcome,
      memoryPromoted: item.memory_promoted,
    })),
  };
}
