export type MetricKey = "exactTokenRecall" | "semanticRelevance" | "coverage" | "diversity" | "metadataMatch" | "freshness";

export interface RetrievalDocument {
  rank: number;
  title: string;
  excerpt: string;
  score: number;
  metadata?: string;
  matched?: boolean;
}

export interface AnalyzerMetric {
  key: MetricKey;
  label: string;
  score: number;
}

export interface StrategyResult {
  name: string;
  score: number;
  latencyMs: number;
  candidates: number;
  winner?: boolean;
}

export interface MemoryInfo {
  hit: boolean;
  pattern: string;
  similarity?: number;
  priorQuery?: string;
  play: string;
  stored: boolean;
  playCaptured: boolean;
  replayAttempted: boolean;
}

export interface RunMetrics {
  latencyMs: number;
  plannerCalls: number;
  retrievalAttempts: number;
  tokens: number;
}

export interface ProviderStatus {
  name: string;
  role: string;
  mode: string;
  called: boolean;
  detail: string;
}

export interface RetrievalRun {
  id: string;
  query: string;
  queryType: string;
  status: "success" | "degraded";
  diagnosis: string;
  diagnosisDetail: string;
  baseline: RetrievalDocument[];
  baselineSkipped: boolean;
  analyzer: AnalyzerMetric[];
  strategies: StrategyResult[];
  memory: MemoryInfo;
  answer: string;
  citations: string[];
  metrics: RunMetrics;
  /** Percentage points measured against the returned baseline, when available. */
  qualityLift: number | null;
  /** True when the API itself is simulating a baseline failure, separate from UI demo mode. */
  backendDemoMode: boolean;
  learned: string[];
  providers: ProviderStatus[];
}

export interface QualityHistoryPoint {
  id: string;
  quality: number;
  baselineQuality: number | null;
  createdAt: string;
}

export interface DashboardData {
  totalRuns: number;
  memoryHitRate: number;
  qualityLift: number | null;
  attemptsSaved: number | null;
  latencySaved: number | null;
  patternsLearned: number;
  qualityHistory: QualityHistoryPoint[];
  recentRuns: Array<{ query: string; diagnosis: string; strategy: string; memoryHit: boolean; outcome?: "success" | "degraded"; memoryPromoted?: boolean }>;
}
