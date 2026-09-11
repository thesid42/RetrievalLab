import { normalizeDashboard, normalizeRun } from "../src/contracts.ts";

function assert(condition, message) {
  if (!condition) throw new Error(`Contract check failed: ${message}`);
}

const dashboardWithNulls = {
  total_runs: 4,
  memory_hit_rate: 0.25,
  patterns_learned: 0,
  average_quality_lift: null,
  attempts_saved_percent: null,
  latency_saved_percent: null,
  average_attempts_discovery: 4,
  average_attempts_replay: 0,
  quality_history: [],
  recent_runs: [],
};
const normalizedDashboard = normalizeDashboard(dashboardWithNulls);
assert(normalizedDashboard.qualityLift === null, "explicit null quality lift must remain unavailable");
assert(normalizedDashboard.attemptsSaved === null, "explicit null attempt savings must remain unavailable");
assert(normalizedDashboard.latencySaved === null, "explicit null latency savings must remain unavailable");

const zeroReplayWithoutFields = normalizeDashboard({ average_attempts_discovery: 0, average_attempts_replay: 0 });
assert(zeroReplayWithoutFields.attemptsSaved === null, "zero replay comparison must not claim 100% attempts saved");
const noReplayYet = normalizeDashboard({ average_attempts_discovery: 4, average_attempts_replay: 0 });
assert(noReplayYet.attemptsSaved === null, "discovery without a replay must not claim 100% attempts saved");
const measuredDashboard = normalizeDashboard({ average_quality_lift: 0.23, attempts_saved_percent: 75, latency_saved_percent: 20 });
assert(measuredDashboard.qualityLift === 23 && measuredDashboard.attemptsSaved === 75 && measuredDashboard.latencySaved === 20, "reported numeric dashboard metrics must map to display units");

const document = (id) => ({
  id,
  title: id,
  content: `Evidence for ${id}`,
  document_type: "incident",
  published_at: "2026-01-01T00:00:00Z",
});
const strategy = (name, quality, latency, id) => ({
  strategy: name,
  quality_score: quality,
  latency_ms: latency,
  results: [{ document: document(id), score: quality, rank: 1 }],
});
const replayWinner = strategy("hybrid", 0.8, 20, "winner");
const replayRaw = {
  run_id: "replay-degraded",
  query: "Why did this fail?",
  query_profile: { query_type: "exact_identifier_troubleshooting" },
  path: "discovery",
  memory_match: { query_pattern: "exact_identifier_troubleshooting", similarity: 0.92, winning_strategy: "hybrid" },
  baseline: strategy("dense", 0.2, 8, "base"),
  baseline_skipped: true,
  diagnosis: { failure_type: "lexical_failure", explanation: "Replay did not meet the quality gate.", signals: {} },
  experiments: [strategy("hybrid", 0.7, 18, "first"), replayWinner],
  winner: replayWinner,
  answer: "No reliable answer.",
  evidence: [],
  planner_calls: 1,
  retrieval_attempts: 2,
  elapsed_ms: 120,
  trace: [],
  integrations: [],
  outcome: "degraded",
  memory_promoted: false,
  play_captured: false,
  replay_attempted: true,
  quality_lift: null,
};
const normalizedRun = normalizeRun(replayRaw);
assert(normalizedRun.status === "degraded", "degraded response must stay degraded");
assert(normalizedRun.qualityLift === null, "failed replay must not invent a baseline lift");
assert(normalizedRun.memory.stored === false && normalizedRun.memory.playCaptured === false, "degraded replay must not report learning");
assert(normalizedRun.learned.length === 0, "degraded replay with no learning events must stay empty");
assert(normalizedRun.strategies.filter((item) => item.winner).length === 1, "duplicate strategy names must mark exactly one winner");

console.log("Frontend API contract checks passed.");
