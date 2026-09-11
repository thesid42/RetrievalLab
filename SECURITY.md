# Security and verification status

This application is a local, single-workspace prototype. Sponsor integrations and shared
deployment have not been security-reviewed in a live environment.

## Implemented boundaries

- Sponsor credentials belong in backend environment variables only.
- The frontend's shared access key is entered for the browser session; never put the
  server key in a `VITE_*` variable, which becomes public build content.
- Retrieved documents are treated as data. Current answers quote selected passages;
  there is no LLM or arbitrary tool interpreter at that boundary.
- Basic text redaction and suspicious-phrase filtering are defense-in-depth heuristics,
  not a guarantee of prompt-injection prevention or complete secret/PII detection.
- Bridge responses must be validated before they change strategies, memory or evidence.
- Remote planning is limited to registered retrieval strategies. Play steps are data;
  the local executor does not evaluate returned code or shell commands.
- Local state and credential files are excluded by `.gitignore`.

Before deploying to multiple users, add per-user data isolation, deployment authentication,
request limits, and a review of all actual sponsor transport/authentication contracts.

## Snyk

The local Snyk CLI is installed in `web/node_modules`. No authenticated Snyk scan has
completed; `.snyk` is a policy file, not evidence that this project is vulnerability-free.

After authenticating, from the repository root:

```powershell
node web/node_modules/snyk/bin/snyk auth
node web/node_modules/snyk/bin/snyk test --file=web/package.json --dev
node web/node_modules/snyk/bin/snyk test --file=backend/constraints.txt --package-manager=pip --command=backend/.venv/Scripts/python.exe
node web/node_modules/snyk/bin/snyk code test
```

The Python snapshot includes runtime and development packages. The installed CLI's help
requires `--package-manager=pip` for custom requirements filenames. Review findings and
save the completed scan evidence before claiming Snyk compliance.
