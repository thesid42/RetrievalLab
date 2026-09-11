# RetrievalLab handoff

Updated: September 11, 2026, 22:25 UTC, live integration repair and native app replay.

## Current handoff: app running, native replay verified

This section supersedes older setup/failure statements below. Earlier evidence is retained
as history, not current acceptance status.

GitHub delivery scope (subsequent user request): integration fixes, local Play source,
tests/docs, and the five-example UI dropdown. Dropdown choices do not execute requests;
AUTH-502 OAuth, current refunds, Renderer 4.2 and duplicate checkout are available alongside
AUTH-431. No additional live examples were run. Credentials, runtime state and generated
Rote index/lint/release files remain local. GitHub source publication is separate from
Rote registry publication; no registry Play was published. Existing untracked
`.github/copilot-instructions.md` and editor-only pipeline layout changes are outside
this delivery. Check Git history/status for the current commit and push state.

- UI: http://localhost:5173 ; API: http://127.0.0.1:8000/api/v1/health . Loopback only,
  development mode, demo fault injection off. Local API access key is not configured;
  do not expose this server publicly. Logs are in `runtime/api-live.*.log` and
  `runtime/web-live.*.log`. Inspect current listener PIDs before stopping anything.
- Latest complete HTTP replay: `27c60b47-9ec3-4f43-a1c9-23ebd6c94d73`, query
  `Why does AUTH-431 happen after enabling SSO?`, outcome `success`, path `replay`,
  one retrieval attempt, baseline skipped, 53,407.61 ms, heuristic quality 0.8341.
  HydraDB returned validated remote memory; RocketRide accepted native dispatch;
  Rote executed the saved Play; actual Hotdata candidates were consumed. No duplicate
  app retrieval ran. Cognee and HydraDB writes were correctly skipped on this replay.
- Hotdata: real corpus has 11 rows. Fixed CSV-inferred numeric `version` and naive UTC
  `published_at` by SQL casts; strict Document validation remains intact. Native candidates
  are ranked locally (`remote+local-ranking`), not provider-side semantic embeddings.
- Cognee Cloud: fixed multipart file field `data`, dataset form field `datasetName`, and
  Cloud camelCase `runInBackground`, `searchType`, `topK`. The approved synthetic AUTH-431
  memory passed add, cognify, and search (`remote-queryable`). Earlier empty add acceptance
  was not real construction and is superseded. The user-created dataset is `retrievallab`.
- HydraDB: migrated obsolete endpoints to API v2 `/context/ingest` and `/query`, with
  `API-Version: 2`, database/collection scope, multipart memory ingestion, response-envelope
  validation, and accepted `id` acknowledgements. Live write was `remote-submitted`;
  subsequent remote recall returned a validated canonical AUTH-431 memory.
- RocketRide's model works in the configured execution environment. Individual native
  plan and replay smoke checks passed. The old combined checker can still hit an SDK
  AttributeError when reusing its task. Do not claim its combined check is green.
- Rote Play: `plays/retrievallab-replay/main.ts`, locally released version 0.0.1 (never
  published). Uses process.exec to run `python -m app.replay_cli`; read-only Hotdata
  retrieval, no memory writes and no recursion through the app HTTP endpoint. Validates
  worker exit status, query, corpus version, strategy, ranks and provider identity.
  Three parameter variants passed, including empty results; invalid strategy failed as
  expected. Release gates passed; portability/shareability is `not_assessed` because the
  Python executable is a caller-supplied parameter. Local `play list --dir .../plays` finds
  the release; keyword search currently returns below-relevance-floor. Absolute Play path
  execution works and is what the app uses. See `plays/README.md`.
- User approved this local Play and AUTH-431 synthetic provider memory writes. Do not run
  additional live write scenarios without appropriate approval. Snyk was explicitly skipped;
  no scan or manifest upload occurred. No Discord message, publication, deployment, commit
  or push was performed in this pass.
- Root `.env` was preserved. Created ignored `backend/.env` with nonsecret local wiring:
  pipeline path/source, provider timeout 60 s, WSL distro `Ubuntu-22.04`, Rote CLI path
  `/home/sid/.local/bin/rote`, approved absolute Play path, Rote timeout 75 s, and Linux
  Python `/mnt/e/Projects/Data Hackathon/runtime/rote-smoke-linux/bin/python`.
  That Linux venv has the backend installed editable; keep Windows `backend/.venv` intact.
- Checks: **77 backend tests passed**, two existing deprecation warnings; Ruff passed.
  Frontend build, API contract and isolated offline demo regression passed. A sandboxed
  test retry hit shared-temp permissions; the final run used a fresh local temp directory.
  Rote evidence:
  `/home/sid/.rote/workspaces/retrievallab-replay-native` response `@1` is recorded CLI
  success; execution history is under `dag-retrievallab-replay-dda41f81`. Typed child exit
  and output are authoritative, not `rote ls` aggregate capture counts.

### Remaining work, in priority order

1. Reliability/latency: the preceding replay `a251e5ae-ed9e-4c7c-a083-871d9e7d2454`
   returned a correct answer using RocketRide/Rote fallbacks. Retry passed natively, but
   that intermittent cause is not proven fixed. Isolate per-request RocketRide task IDs
   from the editor and diagnose SDK task reuse; retain safe diagnostics without secrets.
2. Snyk only if the user changes their explicit skip decision. Security scan not done.
3. Remote Hotdata telemetry table is optional and unconfigured; telemetry is durable SQLite.
4. Public hosting, production auth, browser visual QA, wider approved live scenarios and
   independent retrieval-quality evaluation remain separate from this local verification.
   Extractive answers/token-hash retrieval remain MVP implementations.
5. Preserve existing `.github/`, editor pipeline metadata changes, and recovery stash
   described below. GitHub delivery was subsequently requested; consult Git status/history
   rather than older uncommitted/unpushed statements in this document.

## Latest: RocketRide pipeline merged and tested through Rote

This section supersedes the earlier statement that a pipeline/source are missing.

- Fetched and fast-forwarded `main` from `4ad501b` to Anmol's `debc996`
  (`rockerride pipeline`). GitHub had no pull request; the change was on `main`.
  No push, deployment, or credential edits were performed in this pass.
- The overlap was `.gitignore` and untracked `.claude/rules/rocketride.md`, both
  byte-identical to the incoming versions. A scoped recovery stash remains:
  `86149c6cd14acad18d8f7829c8251e356563a397`, named
  `pre-RocketRide-fast-forward-2026-09-11`. Do not blindly pop it: those versions
  are already present in the merged commit. Existing handoff and `.github/`
  changes were preserved.
- The editor changed only webhook UI metadata and top-level `docRevision` in
  `pipelines/retrievallab_planner.pipe` during testing. That user/editor change
  was preserved; no pipeline node logic was changed by this pass.
- Strengthened `pipelines/check_planner.py`: project-root credential resolution,
  no deployment-key forwarding, isolated test task, request timeouts, explicit
  cleanup, registered-tool plan assertions using the app decoder, replay-ack
  assertions, safe JSON reporting and nonzero failure exits. Added 15 offline
  contract tests in `backend/tests/test_planner_smoke.py`.
- **Live Rote result is PARTIAL, not green:** server connection/start succeeded;
  validation had zero warnings; the plan decoded to `bm25`, `hybrid`,
  `hybrid_rerank`. `execute_play` did not satisfy the acknowledgement decoder and
  failed with `ValueError`. Task termination succeeded, process exit was 1.
  Raw answers were deliberately not logged, so the precise cause (pipeline
  response versus envelope decoding) needs a follow-up diagnostic.
- Rote workspace: `/home/sid/.rote/workspaces/retrievallab-rocketride-20260911`.
  `@19 .stdout.text` = 67 passing tests; `@24 .text` = live JSON report;
  `@25 .exit` = code 1. Query via a WSL login shell from that workspace.
  `rote ls` lists successful *captures* even for timed-out/failed commands;
  inspect the typed exit and report instead of using its aggregate success rate.
- Initial sandboxed pytest failed on temporary-directory permissions, not test
  assertions. Re-running under Rote with new disposable `runtime/pytest-*`
  directories passed all 67 tests. Ruff checks of the new checker/tests passed.
- Windows foreground execution under Rote works for quick tests, but has a
  30-second limit. Its background/PTY attempts stalled and were stopped/timed
  out; no Windows checker process remained at final inspection. The actual
  completed live run used an isolated WSL Python 3.14.3 environment at
  `runtime/rote-smoke-linux`, with the backend installed editable and
  `rocketride==1.3.0`. Windows `backend/.venv` was not replaced or upgraded.
- The configured development endpoint was staging. There was no local
  `ROCKETRIDE_OPENAI_KEY`, but the successful live plan shows a model credential
  was available through the connected execution environment. Do not invent a
  missing-credential diagnosis from the root `.env` alone.
- Next: inspect the replay response safely; fix/verify its JSON contract and
  test the app orchestration path at measured LLM latency. Pipeline path/source
  are not automatically enabled in `backend/.env`. See `pipelines/README.md`.
  Native Rote application capture/replay, other sponsor acceptance, and Snyk
  scans remain open. No native retrieval execution is inferred from a plan.

### Rote reuse handoff (process-only; not a released Play)

- Goal/output: repeat this project's offline and live planner acceptance checks,
  returning separate exit codes and a qualified combined result.
- Caller inputs: project root, Linux Python executable, pipeline/source and test
  inputs (the latter currently fixed in the checker; parameterize before release).
- Semantic stages/responsibility: offline regression assertions; live planner
  lifecycle/response assertions. These are independent process stages.
- Substrate: `process.exec`; no adapter/session or fabricated adapter ID needed.
- Ordering: preflight each runtime/required file before its stage; combine only
  after both results are available. Discovery retries are not reusable stages.
- Consumed values: source files and project development credentials, loaded
  locally; no secrets in argv, captured reports or Play metadata.
- Failure contract: timeout, invalid output, cleanup failure and nonzero exit
  fail the affected stage; a successful capture is not a successful test.
- Presentation: show passed/failed/unavailable per stage and retain evidence
  references; the combined headline remains partial while replay fails.
- Save decision: not yet approved; ask whether to save a reusable Rote Play.
  No pending stub exists because this workspace is process-only. Do not export,
  release or publish without that decision and the Rote authoring/QA gates.

## Latest local setup: Rote and Play

This section supersedes the earlier audit's statements that Rote was not installed or
authenticated. The application integration is still separate from this machine setup.

- Installed in WSL2 `Ubuntu-22.04`, Linux user `sid`: Rote **0.82.0**, Play **0.4.98**,
  Codex CLI **0.154.0**, uv **0.11.1**, Deno **2.7.5**, and the Rote TypeScript SDK.
  Launchers live in `/home/sid/.local/bin`; Rote runtimes live in `/home/sid/.rote`.
- The user completed GitHub sign-in. `rote whoami --check` now succeeds. Never copy
  tokens, browser callback URLs, or Rote credential stores into this repository.
- Play was installed and verified for **WSL Codex only**. Claude Code and OpenCode
  were detected but not selected. Windows Codex was not modified. Tulving/recurring
  Plays remain off. Restart the WSL Codex session to load the installed skills.
- `play preflight --harness codex --json` reports `ready: true`, all seven checks pass,
  and `setup_required: false`. `play-machine describe --json` successfully compiles
  the installed controller (85 states).
- The reviewed official `modiqo/hello@0.2.2` Play completed with exit code 0 and **9/9
  stages OK** at 20:57 UTC. Its public service-status/advisory watch items are not
  installation failures or findings about this application's dependencies.
- Play's optional catalog warm-up encountered an upstream invalid `created_at` on
  `modiqo/assessment-bomb-forecaster`. Installation remained READY; direct Hello
  lookup, inspection, and execution worked. Do not edit that unrelated remote record.
- Installer receipt and recovery reference (inside Ubuntu):
  `/home/sid/.local/state/play-bootstrap/runs/20260911T205336388249Z.md` and `.json`.

Use a **login shell** when invoking these tools from PowerShell. Calling a Linux binary
directly through `wsl -- /absolute/path` can omit `~/.local/bin` from child-process PATH,
misdetect the Windows npm Codex shim, and produce a false-negative Play preflight.

```powershell
wsl -d Ubuntu-22.04 -- bash -lc 'rote whoami --check'
wsl -d Ubuntu-22.04 -- bash -lc 'play preflight --harness codex --json'
# Explicitly executes the reviewed, read-only warm-up:
wsl -d Ubuntu-22.04 -- bash -lc 'rote play run modiqo/hello@0.2.2 --yes'
```

Browser-install repair: the original full installer timed out after 600 seconds while
Playwright attempted a hidden sudo prompt. Linux Chrome **153.0.8010.36** and its OS
dependencies were installed with scoped WSL administrator access; Playwright's dependency
check now reports all dependencies installed. Windows Chrome was not changed. The later
`rote setup --full` retry was bounded and did not complete; browser-backed Rote execution
and its MCP service have **not** been smoke-tested. Hello does not need a browser/daemon.
If full browser setup is needed, run `sudo -v` followed by `rote setup --full` in the same
interactive Ubuntu terminal; the dependency installer requests sudo even when packages
are already present. Do not run the whole Rote setup as root or loosen sudo rules.

GitHub login also waited for `xdg-open`/Linux Chrome to exit before consuming its queued
localhost callback. Closing the login browser window allowed it to complete. The login
process has finished; do not start parallel login/install processes.

Still required: capture/review an application-specific native Play with the app's input
contract, configure `RETRIEVALLAB_ROTE_PLAY_REF`, and bridge the Windows backend to WSL
or explicitly move the backend runtime to Linux. Do not reuse/overwrite the Windows
`backend/.venv` as a Linux venv. The Windows readiness check still reports Rote missing;
that is an environment boundary, not evidence this WSL installation failed. Hello is a
warm-up, not RetrievalLab's replay workflow. No Discord readiness message was sent.

RocketRide: the user reports the Local setup finished, and the offline application check
detects its connection settings. A real `.pipe` and its source ID remain missing; no
RocketRide end-to-end call has been verified. The generated `.rocketride` definitions are
available locally. Preserve the existing `.env`, `.gitignore`, `.claude`, and `.github`
changes from the user's setup. No application source changes or GitHub push occurred in
this Rote setup pass.

## GitHub

Public source repository: https://github.com/thesid42/RetrievalLab (`main`).
The user requested the repository name match the application and requested `Anmol-tech`
as a collaborator. GitHub API verification confirmed `Anmol-tech` has active **write**
access; the invitation is no longer pending. Publication and access were checked on
September 11, 2026.

Local environments, credentials, generated builds and runtime databases are ignored.
The initial import uses the authenticated owner's GitHub no-reply commit email.

## Continue here

Latest work is the native-integration correction pass requested after checking every
provider's environment configuration. Read `INTEGRATIONS.md` first, then run:

```powershell
.\backend\.venv\Scripts\python.exe backend/scripts/check_integrations.py
```

- Removed the invented HTTP bridge implementation. `sponsors.py` is now just imports.
- Hotdata has a default shared API host, real SQL row parsing, local ranking of remote
  candidates, optional telemetry loads, and an explicit dry-run-first corpus loader.
- Cognee uses native add/cognify/search; Hydra uses tenant-scoped memory endpoints.
  Queueing, construction and recall are distinguished; only promoted runs are published.
- RocketRide uses its official SDK with an explicitly configured pipeline/source ID.
  SDK 1.3.0 and aiofiles 25.1.0 are installed and recorded in constraints.
- Rote recall is read-only. Explicit replay can run a reviewed CLI Play; native workflow
  capture still requires Rote workspace setup and a real recorded trace.
- `.env.example` now shows correct native requirements and shared host defaults. The
  readiness script and protected `/api/v1/integrations` endpoint expose no secret values.
- No real `.env` or provider credentials were found. No accounts, data uploads, live
  provider calls, Snyk scans, or deployments were performed. This native-integration
  revision follows the published UI legibility commit `2b48d1d`; use Git history for
  the current source revision.
- Backend regressions, the disposable HTTP demo, Ruff and dependency consistency checks
  pass (52 backend tests), as do the frontend build and API-mapper checks. A narrow UI
  status fix recognizes native calls and labels Snyk unverified; layout is unchanged.
  See `AUDIT_TRIAGE.md` for final check details and remaining acceptance gaps.

Latest UI change: a legibility pass in `web/src/styles.css`, following the initial
GitHub publication above.

- Main reading text is 16-17px at the default browser font setting; regular labels
  are 14-15px and secondary metadata is 12-13px. Sizing uses `rem`.
- Secondary text has stronger contrast; excerpts and provider statuses wrap instead
  of being squeezed into tiny single-line rows.
- Panels, controls and strategy rows have more space. Both navigation tabs remain
  available on mobile; the session-key popup stays above the page content.
- Browser checks used explicit synthetic UI data at 1440px, 390px and 320px widths.
  No horizontal page overflow or visible text below 12px remained in the checked views.
  The normal preview width was restored. No backend behavior or dependencies changed.
- The existing `npm run build` completed successfully. The generic Sites build helper
  was incompatible with the Windows npm wrapper, so the project build was used directly.

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
| Native provider adapters | `backend/app/adapters/{hotdata,cognee,hydra,rocketride,rote}.py` |
| Native setup / readiness | `INTEGRATIONS.md`, `backend/scripts/check_integrations.py` |
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
- `backend/.venv` contains the editable backend package and runtime/dev/native extras.
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
2. Complete native settings in `INTEGRATIONS.md`: credentials, resource IDs, loaded Hotdata
   corpus, Cognee tenant URL, Hydra tenant readiness, and reviewed RocketRide/Rote workflows.
   Do not restore the removed custom `/v1/...` bridge paths.
3. Verify each provider's outputs actually control the next stage and retain call evidence:
   - Cognee structures traces;
   - HydraDB durably serves the graph across sessions;
   - hotdata.dev returns retrieval candidates/analytics;
   - RocketRide orchestrates registered tool execution;
   - actual Rote captures and replays workflows.
4. Rote install/signup and the official Hello warm-up are complete in WSL (see the latest
   setup section). Finish the application-specific native capture/replay and Windows/WSL
   execution bridge. Its Discord readiness message remains a user/account action.
5. Authenticate Snyk and run dependency and source scans using `SECURITY.md`. The local
   CLI and policy file alone do not satisfy the scan requirement.
6. Add independent retrieval evaluation on a larger held-out dataset, real embeddings if
   needed, and measured costs. Current heuristic scores are not accuracy benchmarks.
7. Add per-user isolation/authentication and request controls before shared deployment.
8. Preserve installed/generated artifacts via `.gitignore`. No app hosting or deployment
   has been configured; a GitHub source repository is separate from hosting the application.

Native provider setup, Snyk authentication/scans and deployment remain incomplete.
A local play represented by a strategy and fixed steps is not evidence of native Rote
code capture, and a native submission acknowledgement is not completed provider execution.

## Guardrails for continuation

- Prioritize complete, verified demo loops over adding the proposal's other failure types.
- Preserve user data and credentials; keep secrets out of browser build variables.
- Show empty/error/local/demo/remote states accurately.
- Never report sample chart values as measured performance.
- Evaluate evidence before answering or teaching a play; count every actual attempt.
- Keep `HANDOFF.md`, `README.md`, and `AUDIT_TRIAGE.md` in sync after further changes.
