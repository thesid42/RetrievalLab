import { useEffect, useMemo, useState } from "react";
import {
  Activity, ArrowRight, BrainCircuit, Check, CircleDot,
  Clock3, Database, Gauge, GitBranch, KeyRound, Layers3, Play, RotateCcw, Search,
  ShieldCheck, Sparkles, Zap,
} from "lucide-react";
import { getDashboard, getHealth, hasSessionApiKey, isDemoMode, runRetrieval, setSessionApiKey } from "./api";
import { createSampleRun, exampleQueries } from "./sampleData";
import type { AnalyzerMetric, DashboardData, RetrievalRun } from "./types";

type Source = "api" | "demo" | "offline" | "pending";
type View = "lab" | "insights";

const labelize = (value: string) => value.replaceAll("_", " ");
const scoreTone = (score: number) => score < 45 ? "danger" : score < 70 ? "warn" : "good";

function Brand() {
  return (
    <div className="brand">
      <div className="brand-mark"><BrainCircuit size={20} /></div>
      <div><strong>Retrieval<span>Lab</span></strong><small>SELF-IMPROVING SEARCH</small></div>
    </div>
  );
}

function SessionKeyControl({ onRefresh }: { onRefresh: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [keyValue, setKeyValue] = useState("");
  const [saved, setSaved] = useState(() => hasSessionApiKey());
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  async function saveKey(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = keyValue.trim();
    if (!value) {
      setFeedback("Enter a key or choose Clear.");
      return;
    }
    setSaving(true);
    setFeedback(null);
    setSessionApiKey(value);
    setKeyValue("");
    setSaved(true);
    try {
      await onRefresh();
      setFeedback("Saved for this browser tab; connection refreshed.");
    } catch (reason) {
      setFeedback(reason instanceof Error ? reason.message : "The API connection could not be refreshed.");
    } finally {
      setSaving(false);
    }
  }

  async function clearKey() {
    setSaving(true);
    setSessionApiKey("");
    setKeyValue("");
    setSaved(false);
    setFeedback(null);
    try {
      await onRefresh();
      setFeedback("Session key cleared; connection refreshed.");
    } catch (reason) {
      setFeedback(reason instanceof Error ? reason.message : "The API connection could not be refreshed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={`key-control ${open ? "open" : ""}`}>
      <button type="button" className="key-toggle" aria-expanded={open} aria-controls="session-key-form" onClick={() => { setOpen((current) => !current); setFeedback(null); }}>
        <KeyRound size={13} /> API key{saved ? " · saved" : ""}
      </button>
      {open && <form id="session-key-form" className="key-form" onSubmit={saveKey}>
        <label htmlFor="session-api-key">Session API access key</label>
        <input id="session-api-key" type="password" value={keyValue} onChange={(event) => setKeyValue(event.target.value)} placeholder={saved ? "Enter a replacement key" : "Paste shared key"} autoComplete="off" spellCheck={false} disabled={saving} />
        <div className="key-actions"><button type="submit" disabled={saving || !keyValue.trim()}>{saving ? "Refreshing…" : "Save"}</button><button type="button" className="key-clear" disabled={saving || !saved} onClick={() => void clearKey()}>Clear</button></div>
        <small role={feedback ? "status" : undefined}>{feedback ?? "Stored only for this browser tab."}</small>
      </form>}
    </div>
  );
}

function Header({ view, setView, source, onRefresh }: { view: View; setView: (v: View) => void; source: Source; onRefresh: () => Promise<void> }) {
  const status = source === "api"
    ? { label: "API connected", tone: "live" }
    : source === "demo"
      ? { label: "Synthetic demo", tone: "demo" }
      : source === "pending"
        ? { label: "Connecting…", tone: "pending" }
        : { label: "API unavailable", tone: "offline" };
  return (
    <header className="topbar">
      <Brand />
      <nav>
        <button className={view === "lab" ? "active" : ""} onClick={() => setView("lab")}>Retrieval Lab</button>
        <button className={view === "insights" ? "active" : ""} onClick={() => setView("insights")}>Compounding</button>
      </nav>
      <div className="header-actions"><SessionKeyControl onRefresh={onRefresh} /><div className="status-pill"><i className={status.tone} />{status.label}</div></div>
    </header>
  );
}

function SearchHero({ query, setQuery, onRun, loading }: { query: string; setQuery: (s: string) => void; onRun: () => void; loading: boolean }) {
  return (
    <section className="hero">
      <div className="eyebrow"><Sparkles size={14} /> FROM MEMORY TO MUSCLE MEMORY</div>
      <h1>Watch retrieval <em>debug itself.</em></h1>
      <p>One query. Multiple strategies. Every failure makes the next search smarter.</p>
      <form className="searchbox" onSubmit={(e) => { e.preventDefault(); onRun(); }}>
        <Search size={21} />
        <input aria-label="Retrieval query" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Ask a question that is hard to retrieve…" />
        <kbd>⌘ ↵</kbd>
        <button disabled={loading || !query.trim()} type="submit">
          {loading ? <><span className="spinner" /> Analyzing</> : <><Play size={15} fill="currentColor" /> Run query</>}
        </button>
      </form>
      <div className="examples">
        <label htmlFor="example-query">TRY AN EXAMPLE</label>
        <select
          id="example-query"
          value={exampleQueries.includes(query) ? query : ""}
          onChange={(event) => { if (event.target.value) setQuery(event.target.value); }}
          aria-describedby="example-query-help"
        >
          <option value="" disabled>Choose an example query…</option>
          {exampleQueries.map((example) => <option key={example} value={example}>{example}</option>)}
        </select>
        <small id="example-query-help">Choose an example, then select Run query. Selecting an example does not run it.</small>
      </div>
    </section>
  );
}

function Metric({ metric }: { metric: AnalyzerMetric }) {
  const tone = scoreTone(metric.score);
  return (
    <div className="metric">
      <div className="metric-top"><span>{metric.label}</span><strong className={tone}>{metric.score}</strong></div>
      <div className="meter"><i className={tone} style={{ width: `${metric.score}%` }} /></div>
    </div>
  );
}

function RunResults({ run }: { run: RetrievalRun }) {
  const maxStrategy = Math.max(...run.strategies.map((s) => s.score), 100);
  const hasMeasuredLift = run.qualityLift !== null;
  return (
    <div className="results animate-in">
      <div className="run-header">
        <div><span className="run-id">RUN / {run.id.slice(-8).toUpperCase()}</span><h2>{run.query}</h2></div>
        <div className={`success-badge ${run.status === "degraded" ? "degraded" : ""}`}>
          {run.status === "success" ? <Check size={15} /> : <CircleDot size={15} />}
          {run.status === "success" ? "RESOLVED" : "NEEDS REVIEW"}
        </div>
      </div>
      <div className="run-kpis" aria-label="Measured run metrics">
        <span><strong>{run.metrics.retrievalAttempts}</strong> retrieval attempts</span>
        <span><strong>{run.metrics.plannerCalls}</strong> planner calls</span>
        <span><strong>{run.metrics.latencyMs} ms</strong> total time</span>
        <span><strong>{hasMeasuredLift ? `${run.qualityLift! > 0 ? "+" : ""}${run.qualityLift} pp` : "—"}</strong> heuristic quality lift</span>
      </div>
      {run.backendDemoMode && <div className="demo-notice" role="status"><CircleDot size={14} /> API demo mode: deliberate baseline retrieval faults are enabled.</div>}

      <div className="stage-label"><span>01</span> {run.baselineSkipped ? "Replayed evidence" : "Baseline retrieval"} <i /> <small>{run.baselineSkipped ? "Known play · baseline skipped" : `Dense · top K = ${run.baseline.length}`}</small></div>
      <div className="split-grid">
        <article className="panel evidence-panel">
          <div className="panel-title"><span><Layers3 size={17} /> {run.baselineSkipped ? "Replay results" : "Original results"}</span><small>EVIDENCE SCORE</small></div>
          <div className="documents">
            {run.baseline.map((doc) => (
              <div className={`document ${doc.matched ? "target" : ""}`} key={`${doc.rank}-${doc.title}`}>
                <b>#{doc.rank}</b><div><strong>{doc.title}</strong><p>{doc.excerpt}</p><small>{doc.metadata}</small></div>
                <span>{Math.round(doc.score * 100)}</span>
                {doc.matched && <label>needed evidence</label>}
              </div>
            ))}
          </div>
        </article>

        <article className="panel analyzer-panel">
          <div className="panel-title"><span><Activity size={17} /> Retrieval analyzer</span><small>6 SIGNALS</small></div>
          <div className="metrics">{run.analyzer.map((metric) => <Metric metric={metric} key={metric.key} />)}</div>
          <div className="diagnosis">
            <div><CircleDot size={15} /><span>DIAGNOSIS</span></div>
            <strong>{labelize(run.diagnosis)}</strong>
            <p>{run.diagnosisDetail}</p>
          </div>
        </article>
      </div>

      <div className="stage-label"><span>02</span> {run.baselineSkipped ? "Captured strategy replay" : "Counterfactual strategy race"} <i /> <small>{run.baselineSkipped ? "Planner skipped · captured play" : "Compared alternatives"}</small></div>
      <article className="panel race-panel">
        <div className="race-head">
          <div><h3>Find the best evidence path</h3><p>{run.baselineSkipped ? "Captured play replayed; provider statuses are shown below" : "Strategy alternatives compared; provider statuses are shown below"}</p></div>
          <div className="race-legend"><span><i className="base" /> baseline</span><span><i className="winner" /> winner</span></div>
        </div>
        <div className="race-list">
          {run.strategies.map((strategy, i) => (
            <div className={`strategy ${strategy.winner ? "winning" : ""}`} key={`${strategy.name}-${i}`} style={{ "--delay": `${i * 90}ms` } as React.CSSProperties}>
              <div className="strategy-name"><span>{String(i + 1).padStart(2, "0")}</span><strong>{strategy.name}</strong>{strategy.winner && <label><Sparkles size={12} /> WINNER</label>}</div>
              <div className="strategy-track"><i style={{ width: `${(strategy.score / maxStrategy) * 100}%` }} /></div>
              <strong className="strategy-score">{strategy.score}<small>/100</small></strong>
              <div className="strategy-meta"><Clock3 size={12} /> {strategy.latencyMs} ms <b>·</b> {strategy.candidates} candidates</div>
            </div>
          ))}
        </div>
      </article>

      <div className="stage-label"><span>03</span> Remember &amp; respond <i /> <small>Compounding intelligence</small></div>
      <div className="memory-grid">
        <article className={`panel memory-card ${run.memory.hit ? "memory-hit" : ""}`}>
          <div className="memory-icon">{run.memory.hit ? <Zap size={22} /> : <Database size={22} />}</div>
          <div className="memory-copy">
            <span>{run.memory.hit ? "MEMORY HIT" : run.memory.stored ? "PATTERN PROMOTED" : "PATTERN NOT PROMOTED"}</span>
            <h3>{labelize(run.memory.pattern)}</h3>
            {run.memory.priorQuery && <p>Matched <b>{run.memory.similarity}%</b> to “{run.memory.priorQuery}”</p>}
            <div className="play">
              <GitBranch size={15} />
              <span>{run.memory.replayAttempted ? "Replay attempted" : run.memory.playCaptured ? "Play captured" : "Candidate play"}</span>
              <strong>{run.memory.play}</strong>
            </div>
          </div>
        </article>
        <article className="panel answer-card">
          <div className="panel-title"><span><Sparkles size={17} /> Grounded answer</span><small>{run.citations.length} SOURCES</small></div>
          <p className="answer">{run.answer}</p>
          <div className="citations">{run.citations.map((citation, i) => <span key={citation}>[{i + 1}] {citation}</span>)}</div>
        </article>
      </div>

      <Pipeline run={run} />
    </div>
  );
}

const pipeline = [
  { name: "Cognee", role: "structures memory", icon: BrainCircuit },
  { name: "HydraDB", role: "persists patterns", icon: Database },
  { name: "hotdata.dev", role: "executes live queries", icon: Activity },
  { name: "RocketRide", role: "orchestrates tools", icon: Layers3 },
  { name: "Modiqo Rote", role: "play workflow", icon: RotateCcw },
  { name: "Snyk", role: "scan unverified", icon: ShieldCheck },
];

function Pipeline({ run }: { run: RetrievalRun }) {
  const pipelineCommitted = run.memory.stored;
  const providerSummary = (statuses: RetrievalRun["providers"]) => {
    if (statuses.length === 0) return { mode: "not reported", called: false, detail: "No status was returned for this stage." };
    const calledCount = statuses.filter((status) => status.called).length;
    const nativeCount = statuses.filter((status) => status.called && /^(remote|native)/.test(status.mode)).length;
    const last = statuses[statuses.length - 1];
    const modes = [...new Set(statuses.map((status) => status.mode).filter(Boolean))];
    return {
      mode: modes.length > 1 ? `${last.mode} · ${modes.length} modes` : (last.mode || "reported"),
      called: calledCount > 0,
      detail: `${statuses.length} adapter stages reported; ${calledCount} attempted provider calls; ${nativeCount} native/remote stage reports. Calls and submissions are not proof of completed execution. ${statuses.map((status) => status.detail).filter(Boolean).join(" ")}`,
    };
  };
  return (
    <section className="pipeline">
      <div className="pipeline-heading">
        <span>LEARNING PIPELINE</span>
        <small className={pipelineCommitted ? "" : "muted"}>{pipelineCommitted ? "Memory promotion recorded" : "Observation · no promotion"}</small>
      </div>
      <div className="pipeline-row">
        {pipeline.map(({ name, role, icon: Icon }, index) => {
          const provider = providerSummary(run.providers.filter((item) => item.name === name));
          return (
          <div className="pipeline-step" key={name}>
            <div><Icon size={18} /></div><span title={provider.detail}><strong>{name}</strong><small>{provider.mode === "not reported" ? role : provider.mode}</small></span>{provider.called && <Activity size={14} aria-label="Provider call attempted; inspect status for outcome" />}
            {index < pipeline.length - 1 && <ArrowRight size={15} className="arrow" />}
          </div>
          );
        })}
      </div>
      {run.learned.length > 0 && <div className="learning-log">{run.learned.map((item) => <span key={item}><Check size={12} /> {item}</span>)}</div>}
    </section>
  );
}

function formatHistoryDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(undefined, { month: "short", day: "2-digit" }).toUpperCase();
}

function qualityPath(points: DashboardData["qualityHistory"], field: "quality" | "baselineQuality"): string {
  if (points.length === 0) return "";
  const width = 700;
  const height = 210;
  return points.map((point, index) => {
    const value = field === "quality" ? point.quality : point.baselineQuality;
    const x = points.length === 1 ? width / 2 : (index / (points.length - 1)) * width;
    const y = value == null ? null : height - Math.min(1, Math.max(0, value)) * height;
    return y == null ? "" : `${index === 0 || (field === "baselineQuality" && points[index - 1].baselineQuality == null) ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
  }).filter(Boolean).join(" ");
}

function Insights({ dashboard, source, loading, error }: { dashboard: DashboardData | null; source: Source; loading: boolean; error: string | null }) {
  if (loading && !dashboard) {
    return <main className="insights"><div className="state-card"><span className="spinner" /><h2>Loading compounding data</h2><p>Waiting for measured run history from the API.</p></div></main>;
  }
  if (!dashboard) {
    return <main className="insights"><div className="state-card error-state" role="alert"><Database size={24} /><h2>Compounding data is unavailable</h2><p>{error ?? "Run a query after the API is available to populate this view."}</p></div></main>;
  }
  const history = dashboard.qualityHistory;
  const qualityLine = qualityPath(history, "quality");
  const baselineLine = qualityPath(history, "baselineQuality");
  const cards = [
    ["Retrieval runs", dashboard.totalRuns.toLocaleString(), Activity, "recorded runs"],
    ["Memory hit rate", `${dashboard.memoryHitRate}%`, BrainCircuit, "measured replays"],
    ["Average heuristic quality lift", dashboard.qualityLift == null ? "—" : `${dashboard.qualityLift > 0 ? "+" : ""}${dashboard.qualityLift} pp`, Gauge, dashboard.qualityLift == null ? "no measured baseline" : "over baseline"],
    ["Retrieval attempts saved", dashboard.attemptsSaved == null ? "—" : `${dashboard.attemptsSaved}%`, Zap, dashboard.attemptsSaved == null ? "no replay comparison" : "discovery vs replay"],
    ["Latency saved", dashboard.latencySaved == null ? "—" : `${dashboard.latencySaved}%`, Clock3, dashboard.latencySaved == null ? "no measured comparison" : "discovery vs replay"],
  ] as const;
  return (
    <main className="insights animate-in">
      <div className="insights-title"><div><span className="eyebrow"><Activity size={14} /> COMPOUNDING INTELLIGENCE</span><h1>The system gets better<br /><em>with every search.</em></h1></div><div className="pattern-count"><strong>{dashboard.patternsLearned}</strong><span>retrieval patterns<br />learned</span></div></div>
      <div className="stat-grid">{cards.map(([label, value, Icon, note]) => <article className="stat-card" key={label}><div><span>{label}</span><Icon size={17} /></div><strong>{value}</strong><small>{note}</small></article>)}</div>
      <div className="insights-grid">
        <article className="panel compounding-chart">
          <div className="panel-title"><span><Gauge size={17} /> Heuristic quality trajectory</span><small>{source === "demo" ? "SYNTHETIC DEMO" : "MEASURED HISTORY"}</small></div>
          {history.length > 0 ? <>
            <div className="chart-area"><div className="chart-labels"><span>100</span><span>75</span><span>50</span><span>25</span></div><svg viewBox="0 0 700 210" preserveAspectRatio="none" aria-label="Measured retrieval quality history"><defs><linearGradient id="fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#b7ff50" stopOpacity=".28"/><stop offset="1" stopColor="#b7ff50" stopOpacity="0"/></linearGradient></defs>{qualityLine && <path className="area" d={`${qualityLine} L700 210 L0 210Z`} />}{baselineLine && <path className="baseline-line" d={baselineLine} />}{qualityLine && <path className="line" d={qualityLine} />}</svg></div>
            <div className="chart-footer"><span>{formatHistoryDate(history[0].createdAt)}</span><span>{formatHistoryDate(history[Math.floor((history.length - 1) / 3)].createdAt)}</span><span>{formatHistoryDate(history[Math.floor(((history.length - 1) * 2) / 3)].createdAt)}</span><span>{formatHistoryDate(history[history.length - 1].createdAt)}</span></div>
          </> : <div className="chart-empty"><Gauge size={22} /><strong>No measured history yet</strong><span>Run discovery and replay queries to see quality over time.</span></div>}
        </article>
        <article className="panel recent-card"><div className="panel-title"><span><Clock3 size={17} /> Recent runs</span><small>LIVE</small></div>{dashboard.recentRuns.map((item) => {
          const runLabel = item.outcome === "degraded" ? "DEGRADED" : item.memoryHit ? "REUSED" : item.memoryPromoted ? "LEARNED" : "OBSERVED";
          return <div className="recent-row" key={item.query}><div className={item.memoryHit ? "hit" : item.outcome === "degraded" ? "degraded" : "learn"}>{item.memoryHit ? <Zap size={15} /> : <BrainCircuit size={15} />}</div><div><strong>{item.query}</strong><small>{labelize(item.diagnosis)} · {item.strategy}</small></div><span>{runLabel}</span></div>;
        })}</article>
      </div>
    </main>
  );
}

export default function App() {
  const [view, setView] = useState<View>("lab");
  const [query, setQuery] = useState(exampleQueries[0]);
  const [run, setRun] = useState<RetrievalRun | null>(() => isDemoMode ? createSampleRun(exampleQueries[0]) : null);
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [source, setSource] = useState<Source>(isDemoMode ? "demo" : "pending");
  const [dashboardLoading, setDashboardLoading] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const qualityLift = useMemo(() => run?.qualityLift ?? null, [run]);

  async function refreshDashboard(showError = true): Promise<boolean> {
    setDashboardLoading(true);
    try {
      const result = await getDashboard();
      setDashboard(result.data);
      setSource(result.source);
      if (showError) setError(null);
      return true;
    } catch (reason) {
      setSource("offline");
      if (showError) setError(reason instanceof Error ? reason.message : "Compounding data is unavailable.");
      return false;
    } finally {
      setDashboardLoading(false);
    }
  }

  async function refreshConnection(): Promise<void> {
    if (isDemoMode) {
      // Keep the synthetic surface active while still checking the live health
      // endpoint when the user changes a session key.
      await Promise.allSettled([getHealth(), refreshDashboard(false)]);
      return;
    }
    const [, dashboardReady] = await Promise.all([getHealth(), refreshDashboard(true)]);
    if (!dashboardReady) throw new Error("The API is reachable, but dashboard data could not be loaded.");
  }

  useEffect(() => { void refreshDashboard(); }, []);
  useEffect(() => {
    const listener = (event: KeyboardEvent) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") execute(); };
    window.addEventListener("keydown", listener); return () => window.removeEventListener("keydown", listener);
  });
  async function execute() {
    if (!query.trim() || loading) return;
    setLoading(true);
    setError(null);
    try {
      const result = await runRetrieval(query.trim());
      setRun(result.data); setSource(result.source); setView("lab");
      void refreshDashboard(false);
      requestAnimationFrame(() => document.getElementById("run-output")?.scrollIntoView({ behavior: "smooth", block: "start" }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The retrieval request could not be completed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app-shell">
      <Header view={view} setView={setView} source={source} onRefresh={refreshConnection} />
      {view === "lab" ? <>
        <main><SearchHero query={query} setQuery={setQuery} onRun={execute} loading={loading} />{error && <div role="alert" className="api-error">{error}</div>}<div id="run-output">{run ? <RunResults run={run} /> : <div className="state-card lab-empty"><Search size={24} /><h2>Ready to inspect a retrieval</h2><p>Run a query to see the baseline, diagnosis, strategy race, and measured outcome.</p></div>}</div></main>
        {run && qualityLift !== null && <aside className="floating-lift"><span>HEURISTIC LIFT</span><strong>{qualityLift > 0 ? "+" : ""}{qualityLift}</strong><small>pp</small></aside>}
      </> : <Insights dashboard={dashboard} source={source} loading={dashboardLoading} error={error} />}
      <footer><Brand /><p>Self-debugging retrieval that learns from every search.</p><span>HACKATHON BUILD · 2026</span></footer>
    </div>
  );
}
