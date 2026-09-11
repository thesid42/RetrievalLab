# RetrievalLab for the Data & AI Hackathon
## Self-Debugging Retrieval That Learns From Every Search

> Implementation status, September 11, 2026: this document is the product proposal.
> The implemented stack is Vite/React + FastAPI + a local SQLite store. The retrieval
> vectors are deterministic token-hash proxies, and answer synthesis is extractive.
> Native provider adapters have replaced the initial custom HTTP bridge contracts.
> Account/data setup and live acceptance remain open; see `INTEGRATIONS.md`.
> Demo fault injection must be explicitly enabled.
> See `AUDIT_TRIAGE.md` for implementation findings and `HANDOFF.md` for the current
> continuation plan. Numeric examples below are illustrative, not benchmark results.

## 1. One-Line Pitch

> **RetrievalLab is a self-improving retrieval control plane that detects when AI search fails, tries better retrieval strategies, remembers which fixes worked, and automatically reuses successful search plans for similar future queries.**

The system turns retrieval from a stateless pipeline into a **compounding agent**:

```text
Search
  ↓
Analyze Retrieval Quality
  ↓
Diagnose Failure
  ↓
Try Better Search Strategies
  ↓
Select the Best Evidence Path
  ↓
Answer
  ↓
Remember What Worked
  ↓
Reuse It Next Time
```

The key hackathon story is:

> **The first query requires reasoning. The second similar query should be faster, cheaper, and more reliable because RetrievalLab remembers both the knowledge and the successful retrieval strategy.**

---

## 2. Why This Fits the Hackathon

The hackathon theme is about agents that do not reset after every run.

A normal RAG system often behaves like this:

```text
Query #1 → Vector Search → LLM → Answer
Query #2 → Vector Search → LLM → Answer
Query #3 → Vector Search → LLM → Answer
```

RetrievalLab instead creates **retrieval muscle memory**:

```text
Query #1
  ↓
Dense Retrieval Fails
  ↓
Analyzer Detects Exact-ID Failure
  ↓
Orchestrator Tests:
Dense / BM25 / Hybrid / Rerank
  ↓
Hybrid + Rerank Wins
  ↓
Successful Strategy Is Stored
  ↓
Successful Execution Path Is Captured

--------------------------------

Similar Query #2
  ↓
Recall Prior Failure Pattern
  ↓
Reuse Hybrid + Rerank Strategy
  ↓
Less Re-Reasoning
  ↓
Faster / Cheaper / More Reliable
```

---

## 3. The Core Problem

Current RAG and vector-search systems frequently use one retrieval strategy for many different query types.

But different queries require different retrieval behavior.

Examples:

```text
"How does authentication work?"
→ Semantic vector search

"Why does AUTH-431 happen?"
→ Exact keyword + semantic search

"What is the current refund policy?"
→ Semantic retrieval + freshness filtering

"What changed after Renderer 4.2?"
→ Version metadata + historical comparison

"Why did checkout fail yesterday?"
→ SQL + logs + semantic search + multi-step investigation
```

When retrieval fails, developers often know only that the final answer was wrong.

They do not immediately know whether the problem was:
- embeddings,
- query formulation,
- exact identifiers,
- stale documents,
- metadata,
- ranking,
- redundant chunks,
- or insufficient evidence.

RetrievalLab diagnoses these failures and automatically attempts a repair.

---

## 4. Full Hackathon Architecture

```text
                    USER QUERY
                        │
                        ▼
              ┌────────────────────┐
              │ Query Understanding│
              └─────────┬──────────┘
                        │
                        ▼
              ┌────────────────────┐
              │ Recall Past Memory │
              │  Cognee + HydraDB  │
              └─────────┬──────────┘
                        │
            Seen similar failure before?
                 /               \
               YES               NO
                │                 │
                ▼                 ▼
      Reuse prior strategy   Baseline retrieval
                │                 │
                │                 ▼
                │        Retrieval Analyzer
                │                 │
                │            failure?
                │           /        \
                │         NO          YES
                │          │           │
                │          │           ▼
                │          │   RocketRide Planner
                │          │           │
                │          │    ┌──────┼───────┐
                │          │    ▼      ▼       ▼
                │          │  Dense   BM25   Hybrid
                │          │    │      │       │
                │          │    └──────┼───────┘
                │          │           ▼
                │          │    hotdata.dev
                │          │   parallel execution
                │          │           │
                │          │           ▼
                │          │    Evidence Judge
                │          │           │
                └──────────┴───────────┘
                           │
                           ▼
                    Best Retrieval
                           │
                           ▼
                       Answer
                           │
                           ▼
                 Cognee structures
                 what was learned
                           │
                           ▼
                 HydraDB persists
                 retrieval memory
                           │
                           ▼
                  Rote captures the
                 successful workflow
                           │
                           ▼
                   NEXT SIMILAR QUERY
```

---

## 5. Cognee — Memory Construction

Cognee turns raw retrieval traces into structured memory.

After a successful or failed search, store more than the query and answer:

```text
QueryPattern
  type = exact_identifier_troubleshooting

Identifier
  AUTH-431

FailureType
  lexical_failure

InitialStrategy
  dense_search

WinningStrategy
  hybrid_plus_rerank

UsefulDocument
  auth-431-troubleshooting.md

Outcome
  success
```

Conceptual memory graph:

```text
[Query Pattern]
      │
      ├── suffered_from ──> [Lexical Failure]
      │
      ├── contains ───────> [Exact Identifier]
      │
      └── solved_by ──────> [Hybrid + Rerank]
                                  │
                                  └── retrieved ──> [Correct Evidence]
```

**Cognee's role:** decide what from a retrieval run is worth remembering and shape it into structured memory.

---

## 6. HydraDB — Durable Retrieval Intelligence

HydraDB stores the memory graph over time.

Example:

```text
(AUTH-431 Query)
      │
      ├── type ─────────────> troubleshooting
      │
      ├── failed_with ──────> dense_search
      │
      ├── failure_type ─────> lexical_failure
      │
      └── solved_with ──────> hybrid_rerank
                                 │
                                 └── success_score → 0.94
```

When a future query arrives:

```text
Why does AUTH-502 happen after OAuth login?
```

RetrievalLab can query HydraDB for similar historical patterns:

```text
Similar pattern:
AUTH-431
Dense search failed
Cause: exact-token miss
Successful strategy: Hybrid + Reranker
```

This avoids rediscovering the same fix from scratch.

---

## 7. hotdata.dev — Live Query and Experimentation Layer

hotdata.dev powers the retrieval experiments.

The orchestrator can try:

```text
Strategy A → Dense Vector Search
Strategy B → BM25 / Full-Text Search
Strategy C → Hybrid Search
Strategy D → Metadata + Vector Search
```

These can run independently and in parallel.

```text
                     QUERY
                       │
                       ▼
                 RocketRide
                       │
       ┌───────────────┼───────────────┐
       ▼               ▼               ▼
     Dense           Keyword         Hybrid
       │               │               │
       └─────── hotdata.dev ───────────┘
                       │
                       ▼
                 Result Sets
```

hotdata.dev can also query live retrieval telemetry:

```sql
SELECT
    strategy,
    AVG(relevance_score),
    AVG(coverage_score),
    AVG(latency_ms)
FROM retrieval_runs
WHERE query_type = 'exact_identifier'
GROUP BY strategy;
```

This gives RetrievalLab:
- historical memory from HydraDB,
- live analytical evidence from hotdata.dev.

---

## 8. RocketRide — Retrieval Orchestration

RocketRide receives the analyzer output:

```json
{
  "query_type": "exact_semantic",
  "exact_identifier": "AUTH-431",
  "semantic_relevance": 0.88,
  "exact_token_recall": 0.20,
  "coverage": 0.51,
  "diagnosis": "lexical_failure"
}
```

It decides what to do next:

```text
Diagnosis:
Lexical retrieval failure

Actions:
1. Run BM25
2. Run Hybrid Search
3. Run Dense Search with a larger candidate pool
4. Rerank candidate sets
5. Compare evidence quality
```

RocketRide coordinates:

```text
Analyzer
  ↓
Planner
  ↓
Search Tool Calls
  ↓
Parallel Experiments
  ↓
Evidence Evaluation
  ↓
Winner Selection
  ↓
Final Answer
```

---

## 9. Modiqo Rote — Retrieval Muscle Memory

Once a retrieval repair works, Rote captures the successful path.

Example successful run:

```text
1. Detect exact identifier
2. Search BM25
3. Search dense vectors
4. Merge candidates
5. Rerank
6. Keep top 5
7. Evaluate evidence
8. Generate answer
```

Future similar query:

```text
Why does AUTH-502 occur?
```

Instead of re-planning from scratch, RetrievalLab recognizes the known pattern and reuses the workflow.

```text
Known Pattern:
exact_identifier_troubleshooting

Known Play:
hybrid_identifier_search

Replay:
BM25
  +
Dense
  ↓
Merge
  ↓
Rerank
  ↓
Top 5
```

This is your visible **muscle-memory** effect.

Measure the real differences during the demo:
- planner calls,
- LLM calls,
- retrieval attempts,
- latency,
- token usage.

Do not pre-invent numbers.

---

## 10. Snyk — Security Layer

Use Snyk during development to scan:

```text
Frontend
Backend
Dependencies
Container/configuration
Repository
```

Relevant risks include:
- vulnerable dependencies,
- leaked secrets,
- unsafe tool integrations,
- prompt injection from retrieved documents.

---

## 11. Retrieval Analyzer

For the MVP, calculate six main signals:

```text
1. Exact-token recall
2. Semantic relevance
3. Evidence coverage
4. Result diversity
5. Metadata match
6. Freshness
```

### Exact-token recall

If `AUTH-431` is only found at rank #5, dense search may be over-generalizing the query.

### Semantic relevance

Measures whether results are semantically related.

### Evidence coverage

Asks whether the retrieved chunks actually contain enough information to answer the question.

### Diversity

Detects repetitive top-K results.

### Metadata match

Checks version, region, customer, document type, etc.

### Freshness

Detects when stale information outranks current information.

---

## 12. Failure Types and Repairs

| Failure | Meaning | Repair |
|---|---|---|
| `lexical_failure` | Exact identifier ignored | BM25 / Hybrid |
| `semantic_failure` | Wording differs but meaning matches | Dense search |
| `metadata_failure` | Wrong version/customer/region | Metadata filter |
| `stale_retrieval` | Old evidence outranks current evidence | Freshness-aware retrieval |
| `redundant_results` | Top-K repeats the same information | MMR / diversity |
| `insufficient_evidence` | Results are related but incomplete | Query expansion |
| `poor_ranking` | Correct document is too low | Reranker |
| `complex_query` | One search cannot answer the full question | Query decomposition |
| `contradictory_evidence` | Sources disagree | Skeptic / verification search |

---

## 13. Counterfactual Retrieval

A major feature is **counterfactual retrieval**.

If production used:

```text
Dense Search
Top-K = 5
Quality = 61
```

RetrievalLab tries alternatives:

```text
Dense K=20 + Rerank → 79
BM25                 → 82
Hybrid               → 91
Hybrid + Rerank      → 95
```

Then it selects the winner and stores the successful pattern.

On a similar query later:

```text
HydraDB Recall
      ↓
Known failure pattern
      ↓
Known winning strategy
      ↓
Rote replays workflow
```

---

## 14. Recommended Demo Dataset

Use a small synthetic technical-support corpus:

```text
authentication-guide.md
sso-setup.md
oauth-guide.md
auth-431-troubleshooting.md
auth-502-troubleshooting.md
refund-policy-2024.md
refund-policy-2026.md
renderer-4.1.md
renderer-4.2.md
incident-101.md
incident-102.md
```

Add metadata:

```json
{
  "title": "AUTH-431 Troubleshooting",
  "product": "authentication",
  "version": "4.2",
  "date": "2026-08-01",
  "document_type": "incident"
}
```

---

## 15. Best Demo Sequence

### Demo 1 — First Unknown Query

Ask:

```text
Why does AUTH-431 happen after enabling SSO?
```

Baseline dense search fails.

Analyzer:

```text
Exact-token recall: LOW
Evidence coverage: MEDIUM
Diagnosis: lexical_failure
```

RocketRide launches:
- Dense
- BM25
- Hybrid
- Hybrid + Rerank

hotdata.dev executes them.

Winner:
```text
Hybrid + Rerank
```

Then:
- Cognee structures the successful run.
- HydraDB stores the retrieval pattern.
- Rote captures the successful workflow.

### Demo 2 — Similar Query

Ask:

```text
Why does AUTH-502 happen after login?
```

RetrievalLab finds a similar prior pattern:

```text
Previous pattern:
AUTH-431

Failure:
Dense lexical miss

Successful strategy:
Hybrid + Rerank
```

Instead of experimenting again:

```text
Reusing known retrieval play...
```

Rote replays it.

This proves:

```text
Run #1 → Discover
Run #2 → Remember + Reuse
```

### Demo 3 — Different Failure

Ask:

```text
What is the current refund policy?
```

Dense retrieval returns an old policy.

Analyzer:

```text
Intent: current_information
Newer relevant document exists
Diagnosis: stale_retrieval
```

RocketRide tests:
- Dense
- Dense + date filter
- freshness-weighted search

The winner becomes a new remembered pattern.

---

## 16. UI Layout

```text
┌─────────────────────────────────────────────┐
│ QUERY                                       │
│ Why does AUTH-431 happen after enabling SSO?│
└─────────────────────────────────────────────┘

┌──────────────────┐  ┌──────────────────────┐
│ ORIGINAL SEARCH  │  │ RETRIEVAL ANALYZER   │
│                  │  │                      │
│ #1 Auth guide    │  │ Exact token    LOW   │
│ #2 OAuth         │  │ Relevance       HIGH │
│ #3 SSO           │  │ Coverage        MED  │
│ #4 Login         │  │ Freshness       HIGH │
│ #5 AUTH-431      │  │                      │
│                  │  │ Failure: lexical     │
└──────────────────┘  └──────────────────────┘

┌─────────────────────────────────────────────┐
│ STRATEGY RACE                               │
│ Dense             61                        │
│ BM25              84                        │
│ Hybrid            92                        │
│ Hybrid+Rerank     95  ← winner              │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│ MEMORY                                      │
│ ✓ Pattern stored                            │
│ ✓ Retrieval strategy remembered             │
│ ✓ Successful play captured                  │
└─────────────────────────────────────────────┘
```

On the second query:

```text
MEMORY HIT
Similar retrieval pattern found

Reusing:
hybrid_identifier_search
```

---

## 17. MVP Architecture

```text
Frontend
Next.js
   │
Backend
FastAPI
   │
Query Understanding
+
Retrieval Analyzer
   │
RocketRide
Strategy Orchestration
   │
 ┌─┼───────────────┐
 │ │               │
Dense             BM25
 │                 │
 └── hotdata.dev ──┘
        │
      Hybrid
        │
Evidence Evaluation
        │
Final Answer
        │
Cognee
        │
HydraDB
        │
Rote
```

---

## 18. What to Build in the 8-Hour Sprint

### Must Have

**Search**
- Dense search
- BM25
- Hybrid search

**Analyzer**
- Exact-token recall
- Evidence coverage
- Metadata match
- Freshness

**Orchestration**
- RocketRide chooses and executes alternative strategies.

**Live query / experiment layer**
- hotdata.dev runs retrieval or telemetry queries.

**Memory**
- Cognee structures:
  - query pattern,
  - failure type,
  - winning strategy,
  - useful evidence,
  - outcome.

- HydraDB persists those relationships.

**Muscle memory**
- Rote captures at least one successful retrieval play and replays it for a similar query.

**Security**
- Scan the project with Snyk.

### Nice to Have

- reranker,
- diversity score,
- contradiction detection,
- skeptic agent,
- query decomposition,
- live latency/token comparison.

---

## 19. Why Every Sponsor Is Necessary

### Cognee
Turns retrieval runs into structured memory.

### HydraDB
Stores and queries the long-term graph of retrieval failures and successful strategies.

### hotdata.dev
Provides fast live query and experimentation over retrieval candidates, telemetry, and structured data.

### RocketRide
Orchestrates diagnosis, alternative retrieval plans, evaluation, and tool calls.

### Modiqo Rote
Captures successful workflows and replays them deterministically.

### Snyk
Secures the codebase, dependencies, and integration surface.

---

## 20. Judging Story

Do **not** pitch:

> We built a better RAG system.

Pitch:

> **RAG systems make the same retrieval mistakes repeatedly because each request starts from zero. RetrievalLab diagnoses retrieval failures, experiments with alternative search plans, remembers what solved each failure pattern, and converts successful retrieval behavior into reusable muscle memory.**

Demo the transformation:

```text
FIRST QUERY

Search fails
↓
Diagnose
↓
Experiment
↓
Find winning strategy
↓
Store memory
↓
Capture workflow

SECOND SIMILAR QUERY

Recognize pattern
↓
Recall prior solution
↓
Replay known workflow
↓
Skip rediscovery
```

---

## 21. Strong Final Pitch

> **RetrievalLab is a self-improving retrieval control plane for AI agents. When vector search produces weak evidence, it analyzes why retrieval failed, orchestrates alternative strategies, compares their evidence quality, and selects the strongest path. More importantly, it remembers the failure pattern and successful repair. Cognee structures the experience, HydraDB stores it as durable retrieval memory, hotdata.dev powers live retrieval experiments and analytics, RocketRide orchestrates the recovery process, and Modiqo Rote turns successful paths into reusable deterministic workflows. The result is an AI search system where every failure can make the next search smarter, cheaper, and more reliable.**

---

## 22. Simplest Mental Model

```text
RAG today:

Search
↓
Answer
↓
Forget

RetrievalLab:

Search
↓
Measure
↓
Diagnose
↓
Repair
↓
Answer
↓
Remember
↓
Reuse
↓
Improve
```

> **From retrieval memory to retrieval muscle memory.**
