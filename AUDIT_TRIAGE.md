# RetrievalLab audit and triage

Audit date: September 11, 2026. Advisor: primary task. Executors: three Luna xhigh
agents covering retrieval/state, bridge contracts, and UI/build correctness.

## Architecture verdict

Current live status supersedes the historical merge results below: Hotdata, Cognee,
HydraDB and native Rote retrieval now pass live checks; full AUTH-431 app replay
`27c60b47-9ec3-4f43-a1c9-23ebd6c94d73` passed with native RocketRide dispatch, Rote
evidence consumption and remote HydraDB recall. Rote Play is locally released, not
published. Remaining P1: intermittent provider/SDK replay fallbacks and 53-second latency.
Snyk is explicitly skipped. See the top of `HANDOFF.md` for evidence and remaining work.

Historical merge checkpoint:

Latest merge/test update: Anmol's RocketRide pipeline commit `debc996` is merged.
The stricter checker and 15 new offline cases bring the backend suite to **67
passing tests**. Rote captured a real live planner response, but the subsequent
`execute_play` acknowledgement check failed (exit 1); cleanup succeeded. Treat
replay output/decoder diagnosis as the remaining P1 integration issue, not a
completed native replay. Details and evidence IDs: `pipelines/README.md` and the
latest `HANDOFF.md` section. No agent executor was used in this merge/test pass.

Keep the two-scenario MVP: exact identifiers and current policy evidence. FastAPI plus
Vite/React is the implemented stack; the original document's Next.js diagram is a proposal.
The five sponsor responsibilities remain appropriate. The follow-up integration pass
replaced our custom bridge contracts with native interfaces. Offline validation does not
establish working sponsor accounts or complete hackathon acceptance. The local database,
retrieval proxy and saved-strategy runner still provide the fallback loop.

## Native integration correction pass

Advisor plus three Luna xhigh executors reviewed provider documentation and adapter code.

| Issue | Correction |
|---|---|
| Hotdata dashboard has no custom base URL | Shared `https://api.hotdata.dev` default; token/workspace/database settings |
| Query body and response were invented | Native SQL `columns`/`rows`, remote-only candidates, explicit local ranking |
| Telemetry used a fabricated route | Optional native table loads; SQLite retained; explicit corpus load utility |
| Cognee used generic Bearer bridge auth | Tenant URL, Cloud X-Api-Key or self-hosted bearer; multipart add/cognify/search |
| Hydra used unverified `/v1/cypher` | Documented tenant-scoped memory write/recall; canonical and corpus validation |
| RocketRide treated as REST | Installed official SDK; use/send/terminate; validated plans and honest dispatch status |
| Rote treated as REST; read triggered execution | Native Play CLI on explicit replay only; recall read-only; capture labeled local |
| Partial env setup was unclear | Correct template, stable dotenv paths, native aliases, safe offline readiness report/API |
| Snyk looked like runtime integration | Documented local scan CLI plus OAuth/token requirements; no fabricated runtime URL |

No live credentials were found, accounts provisioned, data uploaded, or authenticated
native calls performed. Read `INTEGRATIONS.md` for the exact remaining setup and Git
history for the source revision. Offline success is not live-provider acceptance.

### Correction-pass validation

- **52 backend tests passed**: native HTTP/SDK/CLI contracts, malicious/malformed data,
  async acknowledgement handling, redaction, safe configuration, and local regressions.
- Disposable HTTP demo passed: discovery, replay, 14-day current policy, unknown-ID
  abstention, shared-key guards, dashboard counts and persistence after restart.
- Ruff and `pip check` passed. RocketRide SDK 1.3.0 call signatures, timeout units, and
  result-envelope fields were checked against the installed package source.
- Hotdata loader dry-run passed: 11 synthetic documents, 3,545 CSV bytes, no network.
- Frontend production build and API-mapper contract checks passed. Status text now
  recognizes native stages and does not equate attempted calls with success or assert
  Snyk was scanned. Sites guidance kept this a narrow change with no layout redesign.
- Preview route returned HTTP 200; the preview opening was queued by the app. No new
  visual browser QA or full live UI/API run is claimed. The preview server was stopped.
  The generic Sites build wrapper failed on Windows; the project's normal build passed.
- The same two non-failing test-stack deprecation warnings remain. No live sponsor or
  authenticated Snyk checks were performed.

## Code findings addressed

Priorities below describe the original defects, not remaining open defects. The local
fixes were reviewed together; they do not establish production or native-provider readiness.

| Priority | Finding | Correction |
|---|---|---|
| P0 | Memory IDs hash query type, ignoring domain; conflicts can teach the wrong pattern | Full-signature identity; remote signature/confidence validation; corpus-version isolation |
| P0 | Strategy-normalized scores judge their own quality; unrelated results can pass | Text-based evidence evaluation, exact-token boundaries, abstention and preference for valid candidate strategies |
| P0 | Answers concatenate stale or unrelated passages | Shared eligible-source selection; archived/current-policy gates; grounded passages for every requested identifier |
| P0 | Malformed bridge data can crash or report remote success | Strict payload validation; explicit acknowledgement, miss/empty semantics and honest execution modes |
| P0 | SQLite writes were not consistently committed | Transaction-managed connections; restart-persistence acceptance check |
| P1 | Replay fallback loses attempts and lookup increments replay counts | Preserve failed attempts; count actual replay execution; validate before accepting the replay |
| P1 | UI mounts sample runs with demo mode disabled | Separate empty/live/demo/error states; explicit backend fault-injection switch |
| P1 | Dashboard infers success and shows artificial trends or savings | Explicit outcomes/promotion/capture; recorded history and aggregates; unavailable metrics stay unavailable |
| P1 | Browser build embeds the shared API key | Session-scoped password control with save/clear and connection refresh; no baked-in frontend credential |
| P1 | Relative state paths vary with launch directory; dependency/build configuration unverified | Consistent path resolution; installed-version constraints and npm lockfile; corrected Windows Vite and TypeScript configuration |
| P2 | Documentation describes an untested proposal as the implemented product | README, handoff, architecture status and security claims aligned with checked code |

Most relevant files: `backend/app/services/{engine,analyzer,state}.py`,
`backend/app/adapters/{sponsors,hotdata}.py`, `backend/app/{config,main,models}.py`,
`web/src/api.ts`, `web/src/contracts.ts`, `web/src/App.tsx`, and both regression suites.

## Original local audit validation

- Backend regression suite: **20 passed**, including positive and missing-evidence
  multi-identifier regressions.
- Ruff across `app`, `tests`, and `scripts`: passed.
- `pip check`: no broken requirements.
- `scripts/verify_demo.py`: passed with disposable SQLite state, no sponsor endpoints.
  Verified discovery, successful replay, current refund answer, unknown-ID abstention,
  HTTP validation/authentication, dashboard counts and replay after app restart.
- Frontend production build: passed; actual TypeScript API-mapper contract checks passed,
  including absent/null metrics, no replay comparison, duplicate strategies and degraded runs.
- Browser: verified initially empty live UI, AUTH-431 discovery, AUTH-502 replay,
  recorded dashboard values and the current refund-policy answer. Provider labels remained
  local/fallback. The session-key control was also verified against a protected local API:
  missing key rejected, synthetic test key accepted, and access rejected again after Clear.
  Browser checks used separate audit databases; preview servers were stopped.

Observed local scenario results (not performance benchmarks):

| Query | Outcome | Retrieval attempts | Discovery planner calls | Evidence |
|---|---|---:|---:|---|
| AUTH-431 | Discovery success; memory and play retained | 4 | 1 | SSO group-name casing |
| AUTH-502 | Validated replay | 1 | 0 | Clock skew / NTP |
| Current refund policy | Discovery success | 4 | 1 | Current 2026 policy: 14 days |
| Unknown AUTH-999 | Degraded; no promotion or capture | 5, including rejected replay | 1 | None |
| AUTH-502 after restart | Validated replay | 1 | 0 | Same correct incident source |

These scenarios explicitly enable backend demo fault injection. They are not evidence that
ordinary retrieval fails by the same amount. No LLM runs locally, so token savings are
unavailable. Cross-run timing and heuristic quality scores are not independent accuracy
or causal speedup measurements.

The installed FastAPI/Starlette test stack emits two non-failing deprecation warnings:
the `httpx` TestClient integration and AnyIO's `BlockingPortal` alias. A future dependency
maintenance pass should address these together; this audit did not upgrade dependencies
solely to silence warnings.

## Remaining work, by priority

### P0: Hackathon submission readiness

The supplied builder guide requires all five technologies to be load-bearing. This
implementation does **not yet establish that requirement**. Native adapters now exist;
configure them and retain real acceptance evidence. Do not substitute an authenticated
submission or local fallback for proof that provider outputs control downstream stages.

| Layer | What is still needed | Acceptance evidence |
|---|---|---|
| Cognee | Actual ingestion / graph construction, not hand-authored local memory alone | Provider-produced entities/relationships used downstream |
| HydraDB | Actual durable graph writes and relationship-aware recall | Stored graph and successful recall after process restart |
| hotdata.dev | CLI/account/data-source setup and actual candidate/analytics queries | Returned query results drive retrieval and evaluation |
| RocketRide | Real registered-tool orchestration, not just a plan or dispatch acknowledgement | Trace of executed retrieval/tool steps and consumed outputs |
| Modiqo / Rote | Install/signup, warm-up play, actual workflow capture and replay | Captured executable path reused without rediscovery |

The builder guide also asks for a Rote hello-world warm-up and a Discord readiness message.
Those user/account actions remain undone; no messages or account changes were made here.

### P1: Security and credible evaluation

- Authenticate Snyk and run the supported dependency/source workflows in `SECURITY.md`;
  fix findings and retain scan evidence. An installed CLI is not a completed scan.
- Add independent held-out retrieval evaluation beyond this small synthetic corpus.
  Consider real embeddings and grounded generation only after the two sponsor-backed
  loops work. Measure real costs before making cost or token-reduction claims.
- Verify real transport/authentication and response contracts against every provider;
  stub contract tests intentionally cannot prove them.

### P2: Deployment and maintenance

- Add user/tenant isolation, deployment authentication and request controls before shared
  deployment. Current state is single-workspace, with an optional shared local API key.
- Preserve source/history in the public `thesid42/RetrievalLab` repository and keep generated
  artifacts and credentials out of version control.
- Address the test-stack deprecations in a separate checked dependency update.

No live native provider calls, account setup, or deployment are part of either local pass.
