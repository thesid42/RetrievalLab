# Local RetrievalLab replay Play

`retrievallab-replay/main.ts` is the user-approved, locally released Rote Play. Its source
is part of this repository; no Rote registry version was published. It executes the
installed backend's read-only `app.replay_cli` worker
through `process.exec`. The worker retrieves real Hotdata rows and ranks them locally;
it never writes Cognee/HydraDB memory or calls the app HTTP endpoint recursively.

On this machine the Windows backend invokes Rote through WSL `Ubuntu-22.04` using
nonsecret settings in ignored `backend/.env`. Secrets remain in the existing root `.env`.
Run manually from WSL:

```bash
/home/sid/.local/bin/rote play run '/mnt/e/Projects/Data Hackathon/plays/retrievallab-replay/main.ts' \
  'python=/mnt/e/Projects/Data Hackathon/runtime/rote-smoke-linux/bin/python' \
  'query=Why does AUTH-431 happen after enabling SSO?' \
  'strategy=hybrid_rerank' 'top_k=5' --output=json
```

Use the reviewed absolute file path: `--yes` is for registry Plays, not local execution.
`rote play list --dir '/mnt/e/Projects/Data Hackathon/plays' --json` lists this release.
The project index contains one Play, but keyword search currently returns no relevant
match; this does not prevent file-path execution. Index/editor artifacts are ignored.

Inputs are required `python` and `query`, optional `strategy` and `top_k` (1–10).
Python must have this backend installed (`pip install -e backend` from repository root).
Execution and presentation failures propagate; the application additionally validates
the worker's schema, query, corpus version, strategy, ranks and provider identity.
Timeouts/failures activate an explicitly reported local retrieval fallback.

Verified: three input/strategy/top-k variants, including a zero-result query, plus an
invalid-strategy failure. Full Windows API replay consumed the native Play's output.
Release gates passed; general shareability is not assessed because the Python executable
is supplied dynamically. This is tested local setup, not a portable deployment package.
