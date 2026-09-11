"""Report missing native setup without network calls, secret values, or provisioning."""

import json
import os

from app.config import PROJECT_ROOT, Settings
from app.services.integration_setup import deprecated_environment_names, integration_readiness


def main() -> None:
    report = {
        "scope": "Offline configuration only; no authentication or native calls checked.",
        "integrations": integration_readiness(Settings()),
        "obsolete_variables_to_replace": deprecated_environment_names(
            (PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env"), dict(os.environ)
        ),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
