"""Offline, credential-safe checks: configured is never a claim of live verification."""

from importlib.util import find_spec
from pathlib import Path
from shutil import which

from app.config import PROJECT_ROOT, Settings


def integration_readiness(settings: Settings) -> list[dict]:
    checks = []

    def add(name: str, fields: tuple[str, ...], note: str, prerequisites=()):
        missing = [f"RETRIEVALLAB_{field.upper()}" for field in fields if not getattr(settings, field)]
        missing.extend(prerequisites)
        checks.append({
            "provider": name,
            "status": "setup-required" if missing else "configured-unverified",
            "missing": missing,
            "detail": note,
            "live_verified": False,
        })

    add("hotdata.dev", ("hotdata_api_key", "hotdata_workspace_id", "hotdata_database_id"),
        "Shared API host is supplied. Load the corpus table before querying; ranking remains local.")
    add("Cognee", ("cognee_api_url", "cognee_api_key"),
        "Use the tenant Connection Details URL, not the dashboard. Cloud: X-Api-Key; self-host: bearer.")
    add("HydraDB", ("hydradb_api_key", "hydradb_tenant_id"),
        "API v2 host is supplied. Tenant ID maps to database; verify database and memory readiness.")
    rocket_prerequisites = []
    if find_spec("rocketride") is None:
        rocket_prerequisites.append("RocketRide Python SDK (install backend[native])")
    if settings.rocketride_pipeline_path and not settings.rocketride_pipeline_path.is_file():
        rocket_prerequisites.append("Existing RocketRide .pipe file")
    add("RocketRide", ("rocketride_api_key", "rocketride_pipeline_path", "rocketride_source_id"),
        "Supply a reviewed pipeline and its input source ID. Configuration is not execution.",
        rocket_prerequisites)
    rote_prerequisites = []
    if settings.rote_wsl_distribution:
        # The Linux CLI path cannot be resolved on the Windows host. This
        # offline check verifies only the launcher, not WSL login or execution.
        if not which("wsl.exe"):
            rote_prerequisites.append("Installed Windows WSL launcher")
    elif not which(settings.rote_cli_path):
        rote_prerequisites.append("Installed Rote CLI")
    add("Rote", ("rote_play_ref",),
        "Complete setup/login and review a Play; local strategy records are not native capture.",
        rote_prerequisites)
    snyk = PROJECT_ROOT / "web" / "node_modules" / "snyk" / "bin" / "snyk"
    checks.append({
        "provider": "Snyk",
        "status": "installed-auth-unverified" if snyk.is_file() else "setup-required",
        "missing": [] if snyk.is_file() else ["Snyk CLI (npm ci in web/)"],
        "detail": "No runtime app URL/key needed. Use snyk auth or SNYK_TOKEN; no scan is implied.",
        "live_verified": False,
    })
    return checks


def deprecated_environment_names(paths: tuple[Path, ...], environ: dict) -> list[str]:
    """Report obsolete names, never their values or unknown environment contents."""
    deprecated = {
        f"RETRIEVALLAB_{provider}_BASE_URL"
        for provider in ("HOTDATA", "COGNEE", "HYDRADB", "ROCKETRIDE", "ROTE")
    } | {"RETRIEVALLAB_ROTE_API_KEY"}
    found = deprecated.intersection(environ)
    for path in paths:
        if path.is_file():
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                key = line.strip().removeprefix("export ").partition("=")[0].strip()
                if key in deprecated:
                    found.add(key)
    return sorted(found)
