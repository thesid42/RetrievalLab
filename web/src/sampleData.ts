import type { DashboardData, RetrievalRun } from "./types";

const examples = [
  "Why does AUTH-431 happen after enabling SSO?",
  "Why does AUTH-502 happen after OAuth login?",
  "What is the current refund policy?",
  "What changed in Renderer 4.2?",
  "Why are duplicate checkout orders created?",
];

export const exampleQueries = examples;

export const sampleDashboard: DashboardData = {
  totalRuns: 1284,
  memoryHitRate: 68,
  qualityLift: 31,
  attemptsSaved: 42,
  latencySaved: 57,
  patternsLearned: 47,
  qualityHistory: [
    { id: "demo-01", quality: 0.61, baselineQuality: 0.61, createdAt: "2026-09-04T10:00:00Z" },
    { id: "demo-02", quality: 0.72, baselineQuality: 0.58, createdAt: "2026-09-06T10:00:00Z" },
    { id: "demo-03", quality: 0.79, baselineQuality: 0.62, createdAt: "2026-09-08T10:00:00Z" },
    { id: "demo-04", quality: 0.91, baselineQuality: 0.64, createdAt: "2026-09-10T10:00:00Z" },
  ],
  recentRuns: [
    { query: examples[0], diagnosis: "lexical_failure", strategy: "Hybrid + Rerank", memoryHit: false },
    { query: examples[1], diagnosis: "lexical_failure", strategy: "Hybrid + Rerank", memoryHit: true },
    { query: examples[2], diagnosis: "stale_retrieval", strategy: "Freshness Weighted", memoryHit: false },
  ],
};

export function createSampleRun(query: string): RetrievalRun {
  const isMemory = /AUTH-502/i.test(query);
  const isFreshness = /current|latest|refund/i.test(query);
  const diagnosis = isFreshness ? "stale_retrieval" : "lexical_failure";
  const winner = isFreshness ? "Freshness Weighted" : "Hybrid + Rerank";
  const scores = isFreshness
    ? [["Dense", 63, 178], ["Date Filter", 84, 201], ["Freshness Weighted", 96, 224]] as const
    : [["Dense", 61, 184], ["BM25", 84, 116], ["Hybrid", 92, 228], ["Hybrid + Rerank", 95, 302]] as const;

  return {
    id: `demo-${Date.now()}`,
    query,
    queryType: isFreshness ? "current_information" : "exact_identifier_troubleshooting",
    status: "success",
    diagnosis,
    diagnosisDetail: isFreshness
      ? "An older policy ranked above the current version. Freshness metadata needs to influence retrieval."
      : "Dense search understood the topic but missed the exact identifier in the highest-ranked evidence.",
    baseline: isFreshness
      ? [
          { rank: 1, title: "Refund Policy (Archived 2024)", excerpt: "Customers may request a full refund within 30 days…", score: 0.89, metadata: "Policy · 2024" },
          { rank: 2, title: "Customer Returns", excerpt: "Guidelines for processing returns and exchanges…", score: 0.82, metadata: "Guide · Oct 2025" },
          { rank: 3, title: "Current Refund Policy (Effective 2026)", excerpt: "The current policy provides a full refund within 14 days…", score: 0.79, metadata: "Policy · 2026", matched: true },
        ]
      : isMemory
        ? [
          { rank: 1, title: "OAuth Login Guide", excerpt: "OAuth authorization code flow exchanges a short-lived code for tokens…", score: 0.91, metadata: "Guide · v4.2" },
          { rank: 2, title: "Authentication Architecture Guide", excerpt: "Authentication requests pass through the identity gateway…", score: 0.88, metadata: "Guide · v4.2" },
          { rank: 3, title: "AUTH-502: OAuth Clock Skew", excerpt: "AUTH-502 occurs after OAuth login when a node clock differs…", score: 0.86, metadata: "Incident · v4.2", matched: true },
        ]
      : [
          { rank: 1, title: "Authentication Guide", excerpt: "Configure session authentication and login policies…", score: 0.91, metadata: "Guide · v4.2" },
          { rank: 2, title: "OAuth Integration", excerpt: "OAuth providers exchange authorization grants…", score: 0.88, metadata: "Guide · v4.1" },
          { rank: 3, title: "SSO Setup", excerpt: "Connect your identity provider and map claims…", score: 0.86, metadata: "Guide · v4.2" },
          { rank: 5, title: "AUTH-431: SSO Group Mapping Failure", excerpt: "AUTH-431 occurs when group names use different letter casing…", score: 0.74, metadata: "Incident · v4.2", matched: true },
        ],
    baselineSkipped: isMemory,
    analyzer: isFreshness
      ? [
          { key: "semanticRelevance", label: "Semantic relevance", score: 88 },
          { key: "coverage", label: "Evidence coverage", score: 62 },
          { key: "metadataMatch", label: "Metadata match", score: 71 },
          { key: "freshness", label: "Freshness", score: 24 },
        ]
      : [
          { key: "exactTokenRecall", label: "Exact-token recall", score: 20 },
          { key: "semanticRelevance", label: "Semantic relevance", score: 88 },
          { key: "coverage", label: "Evidence coverage", score: 51 },
          { key: "diversity", label: "Result diversity", score: 72 },
        ],
    strategies: scores.map(([name, score, latencyMs], index) => ({ name, score, latencyMs, candidates: 20 + index * 8, winner: name === winner })),
    memory: {
      hit: isMemory,
      pattern: diagnosis,
      similarity: isMemory ? 94 : undefined,
      priorQuery: isMemory ? examples[0] : undefined,
      play: isFreshness ? "freshness_aware_policy_search" : "hybrid_identifier_search",
      stored: !isMemory,
      playCaptured: !isMemory,
      replayAttempted: isMemory,
    },
    answer: isFreshness
      ? "The current policy allows eligible purchases to be refunded within 14 days. The archived 2024 policy allowed 30 days."
      : isMemory
        ? "AUTH-502 occurs after OAuth login when an application node's clock differs from the identity provider by more than 60 seconds. Synchronize the nodes with NTP, then retry after existing tokens expire."
        : "AUTH-431 occurs after enabling SSO when the identity provider sends group names with different letter casing than the configured application mappings. Enable case-insensitive group matching or normalize the group claim, then refresh the user's session.",
    citations: isFreshness ? ["refund-policy-2026"] : isMemory ? ["auth-502"] : ["auth-431", "sso-setup"],
    metrics: { latencyMs: isMemory ? 488 : 1240, plannerCalls: isMemory ? 0 : 1, retrievalAttempts: isMemory ? 1 : scores.length, tokens: isMemory ? 820 : 1480 },
    qualityLift: isMemory ? null : isFreshness ? 33 : 34,
    backendDemoMode: false,
    learned: ["Failure pattern structured by Cognee", "Memory persisted to HydraDB", ...(isMemory ? [] : ["Successful workflow captured by Rote"])],
    providers: [
      { name: "Cognee", role: "memory construction", mode: "demo", called: true, detail: "Sample trace" },
      { name: "HydraDB", role: "durable graph", mode: "demo", called: true, detail: "Sample trace" },
      { name: "hotdata.dev", role: "live query", mode: "demo", called: true, detail: "Sample trace" },
      { name: "RocketRide", role: "orchestration", mode: "demo", called: true, detail: "Sample trace" },
      { name: "Modiqo Rote", role: "play capture/replay", mode: "demo", called: true, detail: "Sample trace" },
      { name: "Snyk", role: "security scan", mode: "unverified", called: false, detail: "No completed scan evidence; authenticate and scan before submission" },
    ],
  };
}
