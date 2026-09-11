# RetrievalLab

RetrievalLab explores retrieval that learns from previous runs: inspect evidence, try a
repair, retain a successful strategy, and validate its replay on a similar query.

The local MVP uses **FastAPI + Vite/React + SQLite**. Its two demonstration families are
exact-identifier troubleshooting and current refund-policy evidence.

Source: [thesid42/RetrievalLab](https://github.com/thesid42/RetrievalLab).
This repository publishes the source code, not a hosted application.

## Read this first

- [HANDOFF.md](HANDOFF.md): current state and continuation steps.
- [AUDIT_TRIAGE.md](AUDIT_TRIAGE.md): prioritized findings, fixes, checks and open work.
- [RetrievalLab_Hackathon_Architecture.md](RetrievalLab_Hackathon_Architecture.md):
  original product proposal; illustrative diagrams and numbers are not execution evidence.
- [SECURITY.md](SECURITY.md): implemented boundaries and Snyk commands.
- [INTEGRATIONS.md](INTEGRATIONS.md): native provider settings and remaining live setup.

## What runs locally

The backend provides deterministic token-hash retrieval, BM25, hybrid scoring,
intent-aware reranking, freshness ranking, evidence checks, extractive answers, persistent
memory/play records and run telemetry. The local vectors are a development proxy, not a
trained semantic embedding model. Heuristic quality scores are not independent accuracy
measurements.

The frontend presents returned evidence, diagnoses, strategy attempts, learning outcomes,
provider modes and recorded metrics. Sample UI data is available only through explicit
`VITE_DEMO_MODE=true`.

Native provider adapters replace the old custom bridge contracts. Missing credentials use
explicit local fallbacks. On September 11, live Hotdata retrieval, Cognee graph construction
and search, HydraDB ingestion/recall, RocketRide planning/dispatch, and a saved local Rote
Play were verified. The complete AUTH-431 API replay consumed Rote's real Hotdata evidence
without duplicate retrieval. It took 53.4 seconds; an earlier replay fell back, so reliability
and latency remain follow-up work. See [HANDOFF.md](HANDOFF.md) for exact evidence and limits.

The [RocketRide planner](pipelines/README.md) and [local retrieval Play](plays/README.md)
are included. Rote release is local only, not registry publication. Snyk was explicitly skipped.

## Start from the installed environment

The backend virtual environment and frontend dependencies are already installed.

Terminal 1, from the repository root:

```powershell
cd backend
# Copy only if you need configuration and .env does not exist yet.
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\uvicorn.exe app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2:

```powershell
cd web
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
npm run dev -- --host 127.0.0.1
```

Frontend: http://localhost:5173. API documentation: http://localhost:8000/docs.

Use `RETRIEVALLAB_DEMO_MODE=true` only when demonstrating injected baseline retrieval
failures. This is separate from `VITE_DEMO_MODE=true`, which displays synthetic frontend
responses without executing the backend. Live execution should visibly distinguish these.

If the API uses `RETRIEVALLAB_API_ACCESS_KEY`, enter the access key through the UI's
session control. Do not place backend or sponsor secrets in frontend build variables.

## Reinstall reproducibly

On the audited Windows/Python environment:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c constraints.txt -e ".[dev,native]"
```

`constraints.txt` records the installed versions for Windows/Python 3.14; it is not a
cross-platform lockfile. The project requires Python 3.11 or newer.

For the frontend, use the checked-in npm lockfile and a Node version satisfying the
installed Vite version's engine requirement (the audit machine uses Node 24):

```powershell
cd web
npm ci
```

## Checks

From `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check app tests scripts
.\.venv\Scripts\python.exe scripts/verify_demo.py
.\.venv\Scripts\python.exe scripts/check_integrations.py
```

From `web/`:

```powershell
npm run build
npm run check:contract
```

The scenario script uses disposable local state and explicitly disabled native credentials. It checks
HTTP responses for discovery, replay, the 14-day current refund policy, unknown-ID
abstention and database persistence across an app restart. It does not alter the demo
database or verify remote sponsors. See the audit report for completed check results.

## Demonstration

With explicit backend demo mode and a fresh *separate* state path:

1. Ask **Why does AUTH-431 happen after enabling SSO?** Inspect the baseline,
   selected strategy and captured play. The source describes group-name casing and its fix.
2. Ask **Why does AUTH-502 happen after login?** Expect the validated matching play
   to retrieve the clock-skew source with fewer attempts and no discovery planner call.
3. Ask **What is the current refund policy?** The answer should cite the 2026 policy:
   14 days, not the archived 30-day policy.
4. Ask about an unknown identifier. It should abstain and avoid promoting that run.

The selected strategy and latency are measured results; do not promise a particular
winning strategy or a latency reduction. A replay with no new baseline has no measured
within-run quality lift. Token savings are unavailable because the local runner makes
no model calls.

Set `RETRIEVALLAB_STATE_PATH` to a new file for a fresh demonstration. Do not erase
existing learned state to reset a demonstration.

## Native integration boundaries

Shared hosts and provider-specific authentication are supplied by the native adapters:

| Provider | Implemented interface | Remaining acceptance |
|---|---|---|
| Cognee | Native multipart add, cognify, search | Provider-produced structure used downstream |
| HydraDB | Tenant-scoped add_memory / recall_preferences | Durable remote recall and graph acceptance |
| hotdata.dev | Native SQL query and optional table load | Loaded corpus and real candidate/telemetry evidence |
| RocketRide | Official Python SDK with configured `.pipe` | Reviewed pipeline and consumed tool outputs |
| Rote | Installed CLI, explicit approved Play replay | Account setup and actual native trace capture |

Run `backend/scripts/check_integrations.py` for a credential-safe offline setup report.
Provider tests use mocked native transports; inspect mode and detail fields on each
operation. No provider setup, login, credits or deployment is required for local checks.

See [SECURITY.md](SECURITY.md) for Snyk authentication and scan commands. No completed
Snyk scan is currently claimed.
