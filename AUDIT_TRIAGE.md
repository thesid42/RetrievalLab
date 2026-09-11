# RetrievalLab audit and triage

Audit date: September 11, 2026. Advisor: primary task. Executors: three Luna xhigh
agents covering retrieval/state, bridge contracts, and UI/build correctness.

## Architecture verdict

Keep the two-scenario MVP: exact identifiers and current policy evidence. FastAPI plus
Vite/React is the implemented stack; the original document's Next.js diagram is a proposal.
The five sponsor responsibilities remain appropriate, but current HTTP adapters define
our own bridge contracts. Their existence does not establish working native sponsor
integrations. The local database, retrieval proxy and play runner provide a development
implementation of the loop.

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

## Validation

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

The supplied builder guide requires all five technologies to be load-bearing. This local
implementation does **not yet satisfy that requirement**. Verify the event's native APIs/SDKs
and implement each custom bridge or replace it with a native adapter. Do not point a sponsor
base URL at an invented endpoint.

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

No native provider calls, account setup, or deployment are part of this local audit.
