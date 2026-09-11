# RocketRide planner

`retrievallab_planner.pipe` is the planner added by Anmol's `debc996` commit.
Its source is `webhook_1`. It consumes the JSON contract described in
`../INTEGRATIONS.md` and uses the `openai-5-mini` profile. It chooses registered
retrieval strategies; it does not itself execute Hotdata retrieval or capture a Rote Play.

## Configuration

Keep the editor-managed development connection in the repository-root `.env`:
`ROCKETRIDE_URI` and `ROCKETRIDE_APIKEY`. The LLM node references
`${ROCKETRIDE_OPENAI_KEY}`; configure that secret in the project or RocketRide's
server-side environment. Never commit a literal key in the pipeline. Deployment
credentials are not used by the smoke checker.

When ready to enable this pipeline in the app, set these in `backend/.env` without
overwriting other settings:

```dotenv
RETRIEVALLAB_ROCKETRIDE_PIPELINE_PATH=pipelines/retrievallab_planner.pipe
RETRIEVALLAB_ROCKETRIDE_SOURCE_ID=webhook_1
```

The app's default 12-second total provider timeout may be too short for this LLM
pipeline. Measure latency before choosing `RETRIEVALLAB_REQUEST_TIMEOUT_SECONDS`;
that setting also affects other provider calls. These settings were not enabled
automatically by the merge/test pass.

## Live smoke check

From the repository root in PowerShell:

```powershell
.\backend\.venv\Scripts\python.exe pipelines/check_planner.py
```

This is a real provider test, potentially making two billable model requests. It
uses synthetic inputs, a fresh in-memory pipeline identity, `use_existing=False`,
and a 120-second idle TTL. It validates the structure, checks the application's
actual plan decoder, requires an explicit `execute_play` acknowledgement, and
terminates its own task in `finally`. It prints a credential-safe JSON report;
**nonzero exit is a failed check**, even when validation and planning passed.
An acknowledgement is not evidence of completed retrieval.

Rote is installed in WSL `Ubuntu-22.04`. A separate Linux test environment now
exists at `runtime/rote-smoke-linux`; it does not replace `backend/.venv`. The
successful live transport used Linux Python under `rote proc run --background`,
followed by `rote proc wait` and typed response queries. Windows foreground
commands work, but their 30-second limit truncated the LLM check. Windows
background/PTY attempts were inconclusive and were stopped/timed out; prefer the
Linux environment for further live Rote checks.

## Recorded result — September 11, 2026

Latest result supersedes the historical checkpoint below: standalone plan and execute_play
checks passed, and the full app replay `27c60b47-9ec3-4f43-a1c9-23ebd6c94d73` passed
native dispatch followed by a real Rote Play consuming Hotdata evidence. The pipeline and
source are enabled in ignored `backend/.env`, with a 60-second provider timeout. A prior
app replay fell back and the combined checker can still hit SDK task-reuse errors; this
is not a claim that every repeated request is reliable. See `../HANDOFF.md`.

Historical checkpoint:

- Git main fast-forwarded to `debc996`; no pull request existed.
- Rote workspace: `/home/sid/.rote/workspaces/retrievallab-rocketride-20260911`.
- `@19`: 67 backend tests passed, two existing deprecation warnings.
- `@24 .text`: live validation passed with zero warnings; planner returned
  `bm25`, `hybrid`, `hybrid_rerank`; the `execute_play` acknowledgement check failed
  with `ValueError`; RocketRide cleanup reported `terminated`.
- `@25 .exit`: Linux smoke process exited with code **1**. The overall live test
  did **not** pass. Inspect the replay answer/envelope to distinguish a pipeline
  output-contract issue from a decoder issue before changing either.
- Rote's `ls` success counts describe evidence capture, not the child command's
  exit status or semantic success. No reusable Play was released or published.

The native application capture/replay loop and automatic Windows-to-WSL Play
execution remain separate unfinished work; these tests do not establish them.
