# RetrievalLab handoff

Updated: September 11, 2026. This replaces the pre-audit handoff.

## GitHub

Public source repository: https://github.com/thesid42/RetrievalLab (`main`).
The user requested the repository name match the application and requested `Anmol-tech`
as a collaborator. GitHub API verification confirmed `Anmol-tech` has active **write**
access; the invitation is no longer pending. Publication and access were checked on
September 11, 2026.

Local environments, credentials, generated builds and runtime databases are ignored.
The initial import uses the authenticated owner's GitHub no-reply commit email.

## Continue here

Read `AUDIT_TRIAGE.md` for findings, fixes, verification results and open work, then
`README.md` for the current setup/check commands. The original architecture document
remains a product proposal; its example scores are illustrative.

The user requested an advisor/executor audit with **Luna at xhigh as executor**. The
primary task reviewed the architecture and integration behavior; three Luna xhigh
executors addressed backend retrieval/state, bridge validation, and frontend/build.

## Product and implementation

RetrievalLab searches a synthetic support corpus, evaluates evidence, discovers a better
strategy when needed, stores successful memory and replays matching strategies.

Implemented stack: FastAPI, Vite/React/TypeScript, SQLite. The local vector method hashes
tokens deterministically; it is not a trained embedding model. Answers extract eligible
source text; the local runner has no LLM token usage.

Keep these two MVP failure families:

- Exact identifier: AUTH-431 (SSO group casing) followed by AUTH-502 (clock skew).
- Current policy: the 2026 refund policy allows 14 days; the archived 2024 policy allowed 30.

Unknown or inadequate evidence should return a degraded outcome with no promoted memory
or captured play. A rejected replay should fall back to discovery and count the failed
attempt. Successful replay must survive restarting the app.

## Source map

| Area | Start here |
|---|---|
| App configuration and factory | `backend/app/config.py`, `backend/app/main.py` |
| API and response fields | `backend/app/api/routes.py`, `backend/app/models.py` |
| Query, retrieval, scoring and answer selection | `backend/app/services/engine.py`, `query.py`, `retrieval.py`, `analyzer.py` |
| Durable memories, plays and telemetry | `backend/app/services/state.py` |
| Custom HTTP bridge contracts | `backend/app/adapters/sponsors.py`, `hotdata.py` |
| Frontend API mapping and UI | `web/src/api.ts`, `contracts.ts`, `types.ts`, `App.tsx` |
| Corpus | `backend/app/data/corpus.json` |
| Disposable HTTP scenario check | `backend/scripts/verify_demo.py` |
| Regression and contract checks | `backend/tests/`, `web/scripts/check-api-contract.mjs` |
| Security boundaries and scan commands | `SECURITY.md` |

Important response fields now distinguish actual execution and learning:
`outcome`, `memory_promoted`, `play_captured`, `replay_attempted`,
`baseline_skipped`, `quality_lift`, and per-operation `integrations`.
See the code for the exact contract; avoid deriving success from quality score alone.

## Installed environment

- Windows, Python 3.14, Node 24, npm 11.
- `backend/.venv` contains the editable backend package and all declared runtime/dev deps.
- `backend/constraints.txt` snapshots installed Python versions; it is not a portable lockfile.
- `web/node_modules` and `web/package-lock.json` are present.
- Snyk is installed locally under `web/node_modules`.
- Source was not initially a Git repository. Git was initialized for the user-requested
  public GitHub publication after the local audit.

Existing tests/build checks and their results are recorded in `AUDIT_TRIAGE.md`.
Contract tests use stubs; the disposable scenario uses temporary SQLite state. Neither
proves a native provider integration.

Browser verification used separate `runtime/audit-preview.db` and
`runtime/audit-auth-preview.db` files; the first may contain three synthetic audit queries.
The latter was used only for session-key connection checks. The test key was cleared and
the preview servers were stopped after verification.
The normal `runtime/retrievallab.db` was not used for browser verification.

## Run locally

From the root, backend terminal:

```powershell
cd backend
.\.venv\Scripts\uvicorn.exe app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend terminal:

```powershell
cd web
npm run dev -- --host 127.0.0.1
```

Use the `.env.example` files when configuration is needed, preserving any existing `.env`.
API: http://localhost:8000/docs. UI: http://localhost:5173.

These are separate switches:

- `RETRIEVALLAB_DEMO_MODE=true` explicitly injects baseline faults into local backend
  retrieval. Disable it for normal retrieval.
- `VITE_DEMO_MODE=true` shows synthetic frontend sample responses without executing the API.

`RETRIEVALLAB_STATE_PATH` selects the database. Prefer a new filename for a fresh demo;
do not erase existing learning. No account credentials have been set by the audit.

## Next work, in priority order

1. Read the final audit results. Preserve the verified local acceptance loop while adding
   native integrations; do not spend the next session recreating the local skeleton.
2. Wire actual sponsor APIs/SDKs or implement the custom bridge contracts against those APIs.
   Do not assume our `/v1/...` paths are native sponsor endpoints.
3. Verify each provider's outputs actually control the next stage and retain call evidence:
   - Cognee structures traces;
   - HydraDB durably serves the graph across sessions;
   - hotdata.dev returns retrieval candidates/analytics;
   - RocketRide orchestrates registered tool execution;
   - actual Rote captures and replays workflows.
4. Complete the event's Rote install/signup and hello-world warm-up. Its Discord readiness
   message is a user/account action not performed by this audit.
5. Authenticate Snyk and run dependency and source scans using `SECURITY.md`. The local
   CLI and policy file alone do not satisfy the scan requirement.
6. Add independent retrieval evaluation on a larger held-out dataset, real embeddings if
   needed, and measured costs. Current heuristic scores are not accuracy benchmarks.
7. Add per-user isolation/authentication and request controls before shared deployment.
8. Preserve installed/generated artifacts via `.gitignore`. No app hosting or deployment
   has been configured; a GitHub source repository is separate from hosting the application.

Native provider setup, Snyk authentication/scans and deployment remain incomplete.
A local play represented by a strategy and fixed steps is not evidence of native Rote
code capture, and a bridge acknowledgement is not proof of completed provider execution.

## Guardrails for continuation

- Prioritize complete, verified demo loops over adding the proposal's other failure types.
- Preserve user data and credentials; keep secrets out of browser build variables.
- Show empty/error/local/demo/remote states accurately.
- Never report sample chart values as measured performance.
- Evaluate evidence before answering or teaching a play; count every actual attempt.
- Keep `HANDOFF.md`, `README.md`, and `AUDIT_TRIAGE.md` in sync after further changes.
