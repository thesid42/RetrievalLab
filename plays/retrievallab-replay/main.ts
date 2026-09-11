#!/usr/bin/env -S rote play run
/**
 * @rote-frontmatter
 * ---
 * name: retrievallab-replay
 * description: Replay a learned RetrievalLab retrieval strategy through the installed application CLI; read-only evidence, no memory writes.
 * provenance:
 *   author: RetrievalLab contributors
 * metadata:
 *   rote_version: 0.82.0
 *   version: 0.0.1
 *   status: released
 *   kind: atomic
 *   flow_type: parallel
 *   execution_model: steps_with_presentation
 *   format: typescript
 *   requires_endpoints: []
 *   requires_sessions: false
 *   discoverability:
 *     tags:
 *     - retrievallab
 *     - retrieval
 *     - typescript
 *   hardcode_audit:
 *     schema: 2
 *     suspicion_count: 3
 *     audit_sha256: 80ffff3b14116da851a57d85d762bd181f86af5dc9deeeeda079fe737ded4e60
 *   exploration_model: null
 * parameters:
 * - name: python
 *   param_type: string
 *   required: true
 *   default: null
 *   description: Python executable in an environment with the RetrievalLab backend installed (pip install -e backend).
 *   example: null
 *   valid_values: null
 * - name: query
 *   param_type: string
 *   required: true
 *   default: null
 *   description: Retrieval query, 1-2000 characters. Credentials must never be included.
 *   example: null
 *   valid_values: null
 * - name: strategy
 *   param_type: string
 *   required: false
 *   default: hybrid_rerank
 *   description: Registered retrieval strategy (dense, bm25, hybrid, hybrid_rerank, freshness).
 *   example: null
 *   valid_values: null
 * - name: top_k
 *   param_type: string
 *   required: false
 *   default: '5'
 *   description: Maximum evidence documents, from 1 to 10.
 *   example: null
 *   valid_values: null
 * steps:
 *   retrieve_evidence:
 *     type: process.exec
 *     timeout_ms: 65000
 *     argv:
 *     - env
 *     - $python
 *     - -m
 *     - app.replay_cli
 *     - --query
 *     - $query
 *     - --strategy
 *     - $strategy
 *     - --top-k
 *     - $top_k
 * presentation_fixtures:
 *   retrieve_evidence: resources/presentation-fixtures/retrieval/fixture.yaml
 * ---
 */

const presentationSdk = await import("__ROTE_PRESENTATION_SDK__").catch((cause) => {
  throw new Error(
    "This is a rote steps presentation program. Run it with `rote play run <name>`.",
    { cause },
  );
});
const { FlowOutput, loadPresentationContext, stepName } = presentationSdk;

const out = new FlowOutput();
const ctx = await loadPresentationContext();
out.setRunStatus(ctx.run.status);

const renderedSteps: Record<string, unknown> = {};

// Takes the step handle (not the name) so every `stepName("...")` at the
// call sites stays a literal that lint can verify against `steps:`.
function renderStep(step: ReturnType<typeof ctx.step>): unknown {
  switch (step.outcome.status) {
    case "completed":
      return step.outcome.output.body;
    case "restored": {
      const source = step.outcome.output.source;
      if (source?.status === "partial") {
        return {
          status: "partial",
          body: step.outcome.output.body,
          diagnostics: source.diagnostics,
          additional_diagnostics: source.additional_diagnostics,
        };
      }
      // A clean restored step completed in an earlier run, so it reads like one.
      return step.outcome.output.body;
    }
    case "partial":
      return {
        status: "partial",
        body: step.outcome.output.output.body,
        diagnostics: step.outcome.output.diagnostics,
      };
    case "skipped":
      return { status: "skipped", reason: step.outcome.output.reason };
    case "failed":
      return { status: "failed", message: step.outcome.output.message };
    case "blocked":
      return {
        status: "blocked",
        reason: step.outcome.output.reason,
        blocked_by: step.outcome.output.blocked_by ?? [],
      };
    default:
      // Unreachable while this body matches the SDK. A play exported before a new
      // outcome status was added lands here instead, so name the remedy.
      throw new Error(
        `unsupported step outcome: ${JSON.stringify(step.outcome)}. ` +
          `Re-export the play to regenerate this switch.`,
      );
  }
}
renderedSteps["retrieve_evidence"] = renderStep(ctx.step(stepName("retrieve_evidence")));

const headlinePrefix = (() => {
  switch (ctx.run.status) {
    case "succeeded":
      return "";
    case "partial":
      return "INCOMPLETE: ";
    case "failed":
      return "FAILED: ";
  }
})();
out.human(`${headlinePrefix}Rendered ${Object.keys(renderedSteps).length} step(s).`);
out.summary(`${headlinePrefix}Rendered ${Object.keys(renderedSteps).length} step(s).`);
out.result({
  run_id: ctx.run.run_id,
  status: ctx.run.status,
  complete: ctx.run.status === "succeeded",
  steps: renderedSteps,
});
