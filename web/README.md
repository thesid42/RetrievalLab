# RetrievalLab Web

A demo-ready React dashboard for the RetrievalLab self-debugging retrieval control plane. It makes the hackathon story visible: baseline failure, analyzer diagnosis, parallel strategy race, winning evidence path, and reusable retrieval memory.

## Run locally

```bash
cd web
npm install
cp .env.example .env
npm run dev
```

The app calls:

- `POST /api/v1/retrieval/run` with `{ "query": "…" }`
- `GET /api/v1/dashboard`

By default the browser calls `/api` and Vite proxies those requests to `http://127.0.0.1:8000`, so the frontend works without a local `.env` file. Set `VITE_API_BASE_URL` to use a different backend origin, or set `VITE_API_PROXY` to change the local proxy target.

Live mode does not fall back to fabricated results when the API is unavailable: it shows a clear empty/error state. Set `VITE_DEMO_MODE=true` to intentionally use the built-in synthetic data for presentations; the header labels that source as **Synthetic demo**. Backend `demo_mode` runs are a separate API state and are called out on the run itself.

If the backend requires `RETRIEVALLAB_API_ACCESS_KEY`, open **API key** in the header and save the shared key for the current browser tab. The key is sent only as `X-API-Key` and is never bundled into the build, URL, or logs; **Clear** removes it.

## Expected API shapes

Types are documented in `src/types.ts`. The retrieval response includes baseline documents, analyzer signals, alternative strategy results, memory status, the grounded answer, run metrics, and learning events. The dashboard response includes aggregate compounding metrics and recent runs.

## Demo flow

1. Run `AUTH-431` to show dense retrieval fail, four strategies race, and a new pattern being stored.
2. Run `AUTH-502` to show a memory hit and the prior hybrid retrieval play reused.
3. Run the refund policy query to show stale-retrieval diagnosis and a freshness-aware winner.
