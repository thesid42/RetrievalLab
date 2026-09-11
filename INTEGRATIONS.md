# Native integration setup

Updated September 11, 2026. The invented HTTP bridge contracts have been removed.
Native adapters and offline contract checks are implemented; no live sponsor account has
been authenticated or verified. All credentials stay in `backend/.env` or backend process
environment variables. Never put them in `web/.env`, commit them, or paste them into logs.

## Start tomorrow

1. Preserve any existing `.env`; copy `backend/.env.example` only if it does not exist.
2. Fill in the missing credentials/resource IDs below. Shared hosts already have defaults.
3. Run the offline readiness check from the repository root:

   ```powershell
   .\backend\.venv\Scripts\python.exe backend/scripts/check_integrations.py
   ```

   The same safe report is available at `GET /api/v1/integrations`, protected by the app's
   shared access key when enabled. Neither check sends network requests. "Configured"
   never means authenticated or verified.
4. Use a new `RETRIEVALLAB_STATE_PATH` for live trials and disable both demo switches.
   Inspect every returned integration's `mode`, `called`, and `detail`; retain real call
   evidence. Never use an injected/synthetic success as provider acceptance evidence.

Both root `.env` and `backend/.env` resolve independently of launch directory; backend
values override root values, and process environment overrides both. Explicit Settings
constructor values override environment values for isolated checks. Old `*_BASE_URL`
and `RETRIEVALLAB_ROTE_API_KEY` settings are obsolete, reported by the readiness script,
and no longer activate a made-up bridge.

## Settings by provider

Every field below has a `RETRIEVALLAB_` prefix in `.env.example`.

| Provider | Host/interface | What you supply |
|---|---|---|
| hotdata.dev | Default `https://api.hotdata.dev` | `HOTDATA_API_KEY`, `HOTDATA_WORKSPACE_ID`, `HOTDATA_DATABASE_ID`; loaded `HOTDATA_TABLE` |
| Cognee | Tenant/deployment-specific | `COGNEE_API_URL`, `COGNEE_API_KEY`; `COGNEE_AUTH_MODE=api_key` for Cloud |
| HydraDB | Default `https://api.hydradb.com` | `HYDRADB_API_KEY`, `HYDRADB_TENANT_ID`; optional `HYDRADB_SUB_TENANT_ID` |
| RocketRide | SDK, default `https://api.rocketride.ai` | `ROCKETRIDE_API_KEY`, `ROCKETRIDE_PIPELINE_PATH`, `ROCKETRIDE_SOURCE_ID` |
| Modiqo Rote | Installed, signed-in CLI | `ROTE_CLI_PATH`, reviewed `ROTE_PLAY_REF`; no REST base URL |
| Snyk | Development scan CLI | `snyk auth` or `SNYK_TOKEN`; no app runtime setting |

Recognized provider-native aliases include `HOTDATA_API_KEY`, `HOTDATA_WORKSPACE_ID`,
`HOTDATA_DATABASE_ID`, `HOTDATA_API_URL`, `COGNEE_SERVICE_URL`, `COGNEE_API_KEY`,
`HYDRA_DB_API_KEY` (also `HYDRADB_API_KEY`), `HYDRADB_TENANT_ID`,
`HYDRADB_SUB_TENANT_ID`, `HYDRADB_API_URL`, `ROCKETRIDE_URI`, `ROCKETRIDE_APIKEY`, and
`ROCKETRIDE_AUTH`. Prefer one naming convention; the app-prefixed name wins over an alias.

Remote API URLs require HTTPS and cannot embed credentials, query strings, or fragments.
Loopback HTTP is allowed for local development. Only override hosts with a trusted provider
endpoint; entering credentials and enabling an adapter allows run data to reach that service.
RocketRide additionally accepts WSS, or WS for loopback runtimes.

## Hotdata: no dashboard base URL needed

The service has a shared host; workspace/database IDs scope requests. The adapter sends
native SQL with Bearer authentication and workspace/database headers. Returned
`columns`/`rows` supply the actual candidates; BM25/hash-vector/reranking still runs locally.
This is not native vector search. See [core concepts](https://www.hotdata.dev/docs/core-concepts)
and the [query contract](https://www.hotdata.dev/docs/api-reference/query).

Default table: `default.main.retrieval_documents`. Required columns:
`id`, `title`, `content`, `product`, `version`, `published_at`, `document_type`, `tags`.
Dates must include a timezone; tags may be an array or a JSON-array string. Use the checked-in
synthetic corpus first. Keep the configured local corpus/version aligned with the remote
dataset; change the state path when changing data sources to avoid reusing old learning.

`backend/scripts/hotdata_load.py` prepares a small inline CSV load and is dry-run-first;
read `--help` before applying it. It never provisions a workspace/database. Applying a
replacement requires explicit replacement approval. Review the exact target first.
Hotdata creates a table on its first replace load, not through SQL DDL. See
[supported data loading](https://www.hotdata.dev/docs/push-data).

Telemetry stays in SQLite unless `HOTDATA_TELEMETRY_TABLE` is configured. Native telemetry
uses a table load, not `/v1/query/telemetry`. Prepare that table with the expected schema
before appending. This small-demo path publishes per run; batch loads before scaling.

## Cognee: use Connection Details

After provisioning the Cloud tenant, copy its URL from API-key Connection Details.
Cloud uses `X-Api-Key`; authenticated self-hosting uses `COGNEE_AUTH_MODE=bearer` with
the appropriate session token. Do not use the dashboard URL. See
[Cloud API keys](https://docs.cognee.ai/cognee-cloud/ui/api-keys).

The adapter performs multipart [add](https://docs.cognee.ai/api-reference/add/add),
blocking [cognify](https://docs.cognee.ai/api-reference/cognify/cognify), then a bounded
[search](https://docs.cognee.ai/api-reference/search/search). Only newly promoted runs
are submitted. Submitted, constructed, and queryable are separate statuses. Canonical
application memory remains authoritative; merely storing that memory in Cognee does not
yet establish that Cognee-produced entities/relationships control downstream decisions.

## HydraDB: tenant scope, not an invented Cypher route

Provision a tenant and ensure its infrastructure is ready. The implemented HTTP adapter
targets the official tenant-scoped [REST API reference](https://docs.hydradb.com/api-reference):
`/memories/add_memory` and `/recall/recall_preferences`. It does not target `/v1/cypher`.
If your event account exposes a different database-scoped API version, confirm that
version with the sponsor before changing the endpoint or IDs.

Only quality-gated promoted memories are queued. Queue acknowledgement does not establish
queryability. Recall validates the exact signature, canonical identity, corpus version,
and confidence. An explicit empty remote recall is a miss, not permission to revive stale
local memory. Transport failures use the labeled SQLite fallback. Graph/Cypher-specific
hackathon acceptance still needs a sponsor-backed demonstration.

## RocketRide: SDK plus a real pipeline

`rocketride==1.3.0` is installed in the project virtual environment as the optional
`native` extra. Reinstall using:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -c constraints.txt -e ".[dev,native]"
```

Create/export a reviewed `.pipe` with RocketRide's tools, then set its file path (relative
paths resolve from the repo root) and input source node ID. Account portal URLs are not
runtime endpoints. The adapter uses the [official SDK](https://cloud.rocketride.ai/sdk)
`use`, `send`, and `terminate` lifecycle, with bounded calls and a lazy import.

The application's pipeline input is JSON with `operation=plan`, `query`, `profile`,
`diagnosis`, and `registered_tools`, or `operation=execute_play`, `query`, `profile`,
and `play`. A planning pipeline should return `strategies`, a list drawn only from its
registered tools. This is an application-owned payload contract, not a RocketRide REST API.
No pipeline is fabricated from guessed node definitions. A valid native plan influences
the attempted strategies. Replay dispatch does not prove tool-step completion; the app
still retrieves and validates evidence through Hotdata/local fallback afterward.

## Rote: reviewed executable Play, not an API token

Follow the sponsor's [release/setup instructions](https://github.com/modiqo/rote-releases)
and [Play tooling](https://github.com/modiqo/play). Complete the event warm-up, login,
and capture/review workflow yourself. No installer, account changes, OAuth approval, or
Discord readiness message has been performed here. Confirm that your installed Play CLI
supports `rote play run` and the documented JSON/noninteractive flags.

The app looks up its local saved strategy without running external code. At actual replay,
an explicitly configured Play is invoked with `query`, `query_pattern`, and `strategy`
parameters; your approved Play must declare those inputs. Configuring `ROTE_PLAY_REF`
opts into executable code, so pin a reviewed version. The command uses an argument vector,
not a shell, and has a timeout; this is not a sandbox for the Play itself.

Native capture still requires a recorded workspace trace. `play_captured` in the API
describes the durable local strategy record, not a native Rote artifact. CLI completion
and retrieval success are separate. Do not wire a Play back to this endpoint recursively.

## Snyk and acceptance

The Snyk CLI is already installed in `web/node_modules`. Follow [SECURITY.md](SECURITY.md)
for OAuth/token setup and dependency/source scans. No authenticated scan is claimed.

Before declaring the hackathon integrations complete, retain evidence that every sponsor
is load-bearing: remote candidates used; provider-produced memory used downstream;
durable remote recall across restart; actual orchestrated tool outputs consumed; and a
captured native Rote workflow replayed successfully. Contract tests alone cannot prove this.
