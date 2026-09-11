r"""Exercise the local HTTP contract with disposable state and no sponsor credentials.

Run from backend/: .\.venv\Scripts\python.exe scripts/verify_demo.py
This is a local scenario check, not a sponsor integration verification.
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def execute(client: TestClient, query: str) -> dict:
    response = client.post("/api/v1/retrieval/run", json={"query": query})
    assert response.status_code == 200, response.text
    run = response.json()
    print(json.dumps({
        "query": query,
        "path": run["path"],
        "outcome": run["outcome"],
        "diagnosis": run["diagnosis"]["failure_type"],
        "winner": run["winner"]["strategy"],
        "evidence": [item["document"]["id"] for item in run["evidence"]],
        "planner_calls": run["planner_calls"],
        "retrieval_attempts": run["retrieval_attempts"],
        "memory_promoted": run["memory_promoted"],
        "play_captured": run["play_captured"],
    }))
    assert all("remote" not in provider["mode"] for provider in run["integrations"])
    return run


def main() -> None:
    with TemporaryDirectory(prefix="retrievallab-audit-") as directory:
        settings = Settings(
            _env_file=None,
            environment="development",
            state_path=Path(directory) / "state.db",
            demo_mode=True,
            api_access_key=None,
            cognee_base_url=None,
            hydradb_base_url=None,
            hotdata_base_url=None,
            rocketride_base_url=None,
            rote_base_url=None,
        )
        with TestClient(create_app(settings)) as client:
            assert client.get("/api/v1/health").status_code == 200
            assert client.post("/api/v1/retrieval/run", json={"query": "   "}).status_code == 422
            first = execute(client, "Why does AUTH-431 happen after enabling SSO?")
            assert first["outcome"] == "success" and first["path"] == "discovery"
            assert first["evidence"][0]["document"]["id"] == "auth-431"
            assert first["memory_promoted"] and first["play_captured"]

            second = execute(client, "Why does AUTH-502 happen after login?")
            assert second["path"] == "replay" and second["outcome"] == "success"
            assert second["evidence"][0]["document"]["id"] == "auth-502"
            assert second["planner_calls"] == 0 and second["retrieval_attempts"] == 1

            policy = execute(client, "What is the current refund policy?")
            assert policy["outcome"] == "success"
            assert policy["evidence"][0]["document"]["id"] == "refund-policy-2026"
            assert "14 days" in policy["answer"] and "30 days" not in policy["answer"]

            unknown = execute(client, "Why does AUTH-999 happen?")
            assert unknown["outcome"] == "degraded" and not unknown["memory_promoted"]
            assert not unknown["play_captured"]
            dashboard = client.get("/api/v1/dashboard")
            assert dashboard.status_code == 200, dashboard.text
            assert dashboard.json()["total_runs"] == 4

        with TestClient(create_app(settings)) as client:
            persisted = execute(client, "Why does AUTH-502 happen after login?")
            assert persisted["path"] == "replay"
            assert client.get("/api/v1/dashboard").json()["total_runs"] == 5

        protected = settings.model_copy(update={"api_access_key": "local-audit-access-key"})
        with TestClient(create_app(protected)) as client:
            assert client.get("/api/v1/dashboard").status_code == 401
            assert client.get("/api/v1/dashboard", headers={"X-API-Key": "wrong"}).status_code == 401
            assert client.get(
                "/api/v1/dashboard", headers={"X-API-Key": "local-audit-access-key"}
            ).status_code == 200

    print("PASS: HTTP demo, abstention, input/auth checks, dashboard and restart persistence")


if __name__ == "__main__":
    main()
