# Local Rote replay contract

Save approved by the user on September 11, 2026. Local only; no registry publication.

- Goal/output: execute the learned retrieval strategy and return validated evidence,
  measured quality, provider mode, query signature and corpus version.
- Inputs: Python executable for an installed RetrievalLab backend, query, strategy,
  and top_k (default 5). Credentials are loaded from the existing backend configuration.
- Semantic stage: `retrieve_evidence`, a finite process running `python -m app.replay_cli`.
- Responsibility: read-only candidate retrieval and deterministic ranking; no memory
  writes, application HTTP recursion, or RocketRide planning inside this stage.
- Substrate: local application CLI, recorded as Rote `process.exec`.
- Ordering: one effect stage, followed by presentation of its structured output.
- Consumed values: caller inputs and configured corpus/provider settings. No secrets
  in Play parameters, package files, or output metadata.
- Failure: invalid inputs and process errors fail the Play; optional provider
  unavailability remains explicitly labelled local fallback. Empty evidence stays empty.
- Presentation: structured `retrievallab.replay.v1` result; no successful claim when
  the process or required output contract fails. The application validates the result
  against the requested query, strategy and current corpus before using it.
