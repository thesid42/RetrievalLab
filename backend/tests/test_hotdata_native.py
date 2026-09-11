from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from typing import Any

import httpx

from app.adapters.hotdata import HotdataQueryEngine, build_candidate_sql
from app.config import Settings
from app.models import QueryProfile, StrategyName
from app.services.query import understand_query
from app.services.retrieval import Corpus


def run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def settings(tmp_path: Path, **kwargs: Any) -> Settings:
    return Settings(_env_file=None, state_path=tmp_path / "state.db", **kwargs)


def native_row(document_id: str = "remote-1") -> list[Any]:
    return [
        document_id,
        "Remote document",
        "AUTH-431 troubleshooting evidence",
        "RetrievalLab",
        "1.0",
        "2025-01-01T00:00:00Z",
        "guide",
        ["authentication"],
    ]


def test_native_query_posts_documented_path_headers_and_rows(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "columns": [
                    "id",
                    "title",
                    "content",
                    "product",
                    "version",
                    "published_at",
                    "document_type",
                    "tags",
                ],
                "rows": [native_row()],
            },
            request=request,
        )

    configured = settings(
        tmp_path,
        hotdata_api_url="https://hotdata.test",
        hotdata_api_key="secret-token",
        hotdata_workspace_id="work-123",
        hotdata_database_id="db-123",
    )
    engine = HotdataQueryEngine(configured, Corpus(configured.corpus_path), transport=httpx.MockTransport(handler))
    strategy_run, status = run(
        engine.execute(understand_query("Why does AUTH-431 happen?"), StrategyName.BM25, 3)
    )

    assert status.mode == "remote+local-ranking"
    assert [item.document.id for item in strategy_run.results] == ["remote-1"]
    assert len(requests) == 1
    request = requests[0]
    assert request.url.path == "/v1/query"
    assert request.headers["Authorization"] == "Bearer secret-token"
    assert request.headers["X-Workspace-Id"] == "work-123"
    assert request.headers["X-Database-Id"] == "db-123"
    body = json.loads(request.content)
    assert body.keys() == {"sql"}
    assert 'FROM "default"."main"."retrieval_documents"' in body["sql"]
    assert "LIMIT 15" in body["sql"]


def test_candidate_sql_escapes_literals_and_rejects_unsafe_identifiers() -> None:
    profile = QueryProfile(
        raw_query="O'Reilly _100% ; DROP TABLE docs",
        normalized_query="O'Reilly _100% ; DROP TABLE docs",
        query_type="test",
        signature="test:literal",
        domain="test",
        terms=["O'Reilly", "_100%", "docs"],
    )
    sql = build_candidate_sql(profile, "default.main.docs", 4)
    assert "O''Reilly" in sql
    assert "\\_100\\%" in sql
    assert "; DROP TABLE" not in sql

    try:
        build_candidate_sql(profile, "default.main.docs;DROP", 4)
    except ValueError:
        pass
    else:
        raise AssertionError("unsafe table identifier was accepted")


def test_candidate_sql_redacts_secrets_and_email_addresses() -> None:
    secret = "sk-prod-abcdefghijklmnop"
    email = "alice@example.com"
    profile = QueryProfile(
        raw_query=f"Find the issue for {secret} and {email}",
        normalized_query="find the issue",
        query_type="test",
        signature="test:sensitive",
        domain="test",
        terms=[secret, email],
    )
    sql = build_candidate_sql(profile, "default.main.docs", 4)
    assert secret not in sql
    assert email not in sql


def test_malformed_or_empty_native_rows_are_transparent(tmp_path: Path) -> None:
    responses = [
        {"columns": ["id"], "rows": [["bad"]]},
        {
            "columns": [
                "id",
                "title",
                "content",
                "product",
                "version",
                "published_at",
                "document_type",
                "tags",
            ],
            "rows": [],
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses.pop(0), request=request)

    configured = settings(
        tmp_path,
        hotdata_api_url="https://hotdata.test",
        hotdata_api_key="secret-token",
        hotdata_workspace_id="work-123",
        hotdata_database_id="db-123",
    )
    engine = HotdataQueryEngine(configured, Corpus(configured.corpus_path), transport=httpx.MockTransport(handler))
    profile = understand_query("Why does AUTH-431 happen?")
    malformed_run, malformed_status = run(engine.execute(profile, StrategyName.BM25, 2))
    assert malformed_status.mode == "local-fallback"
    assert malformed_run.results

    empty_run, empty_status = run(engine.execute(profile, StrategyName.BM25, 2))
    assert empty_status.mode == "remote+local-ranking"
    assert empty_run.results == []


def test_no_credentials_does_not_attempt_network(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, request=request)

    configured = settings(tmp_path)
    engine = HotdataQueryEngine(configured, Corpus(configured.corpus_path), transport=httpx.MockTransport(handler))
    _, status = run(engine.execute(understand_query("Why does AUTH-431 happen?"), StrategyName.DENSE, 2))
    assert status.mode == "local-fallback"
    assert status.called is False
    assert calls == 0


def test_configured_telemetry_uses_documented_table_load(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "arrow_schema_json": "{\"fields\":[]}",
                "connection_id": "conn-1",
                "row_count": 2,
                "schema_name": "main",
                "table_name": "retrieval_telemetry",
            },
            request=request,
        )

    configured = settings(
        tmp_path,
        hotdata_api_url="https://hotdata.test",
        hotdata_api_key="secret-token",
        hotdata_workspace_id="work-123",
        hotdata_database_id="db-123",
        hotdata_telemetry_table="default.main.retrieval_telemetry",
    )
    engine = HotdataQueryEngine(configured, Corpus(configured.corpus_path), transport=httpx.MockTransport(handler))
    status = run(engine.record_telemetry({"run_id": "run-1", "quality": 0.8}))
    assert status.mode == "remote"
    assert requests[0].url.path == "/v1/databases/db-123/schemas/main/tables/retrieval_telemetry/loads"
    body = json.loads(requests[0].content)
    assert body["mode"] == "append"
    assert body["format"] == "csv"
    assert "quality,run_id" in body["data"]


def test_native_query_rejects_transport_error_truncation_duplicate_and_naive_date(
    tmp_path: Path,
) -> None:
    responses = [
        httpx.Response(503, json={"error": {"code": "busy"}}),
        httpx.Response(
            200,
            json={
                "columns": ["id", "title", "content", "product", "version", "published_at", "document_type", "tags"],
                "rows": [native_row()],
                "truncated": True,
            },
        ),
        httpx.Response(
            200,
            json={
                "columns": ["id", "title", "content", "product", "version", "published_at", "document_type", "tags"],
                "rows": [native_row(), native_row()],
            },
        ),
        httpx.Response(
            200,
            json={
                "columns": ["id", "title", "content", "product", "version", "published_at", "document_type", "tags"],
                "rows": [native_row()[:5] + ["2025-01-01", *native_row()[6:]]],
            },
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        response = responses.pop(0)
        response.request = request
        return response

    configured = settings(
        tmp_path,
        hotdata_api_url="https://hotdata.test",
        hotdata_api_key="secret-token",
        hotdata_workspace_id="work-123",
        hotdata_database_id="db-123",
    )
    engine = HotdataQueryEngine(configured, Corpus(configured.corpus_path), transport=httpx.MockTransport(handler))
    profile = understand_query("Why does AUTH-431 happen?")
    for _ in range(4):
        run_result, status = run(engine.execute(profile, StrategyName.BM25, 2))
        assert status.mode == "local-fallback"
        assert run_result.results


def test_native_load_rejects_empty_or_malformed_ack(tmp_path: Path) -> None:
    responses = [
        httpx.Response(200, json={}),
        httpx.Response(202, json={"id": "job-1", "status": "pending"}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        response = responses.pop(0)
        response.request = request
        return response

    configured = settings(
        tmp_path,
        hotdata_api_url="https://hotdata.test",
        hotdata_api_key="secret-token",
        hotdata_workspace_id="work-123",
        hotdata_database_id="db-123",
        hotdata_telemetry_table="default.main.retrieval_telemetry",
    )
    engine = HotdataQueryEngine(configured, Corpus(configured.corpus_path), transport=httpx.MockTransport(handler))
    for _ in range(2):
        status = run(engine.record_telemetry({"run_id": "run-1", "quality": 0.8}))
        assert status.mode == "local-fallback"
        assert status.called is True


def test_native_load_reports_submitted_background_job(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            202,
            json={"id": "job-1", "status": "pending", "status_url": "/v1/jobs/job-1"},
            request=request,
        )

    configured = settings(
        tmp_path,
        hotdata_api_url="https://hotdata.test",
        hotdata_api_key="secret-token",
        hotdata_workspace_id="work-123",
        hotdata_database_id="db-123",
        hotdata_telemetry_table="default.main.retrieval_telemetry",
    )
    engine = HotdataQueryEngine(configured, Corpus(configured.corpus_path), transport=httpx.MockTransport(handler))
    status = run(engine.record_telemetry({"run_id": "run-1", "quality": 0.8}))
    assert status.mode == "remote-submitted"
    assert "background" in status.detail.lower()


def test_loader_dry_run_uses_settings_aliases_without_printing_credentials(
    monkeypatch: Any, capsys: Any
) -> None:
    script_path = Path(__file__).parents[1] / "scripts" / "hotdata_load.py"
    spec = importlib.util.spec_from_file_location("hotdata_load_test", script_path)
    assert spec is not None and spec.loader is not None
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    monkeypatch.setenv("RETRIEVALLAB_HOTDATA_API_URL", "https://alias.test")
    monkeypatch.setenv("RETRIEVALLAB_HOTDATA_WORKSPACE_ID", "workspace-env")
    monkeypatch.setenv("RETRIEVALLAB_HOTDATA_DATABASE_ID", "database-env")
    monkeypatch.setenv("RETRIEVALLAB_HOTDATA_API_KEY", "do-not-print-this-secret")

    exit_code = loader.main(["--corpus", str(Path(__file__).parents[1] / "app" / "data" / "corpus.json")])
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "https://alias.test/v1/databases/database-env" in output
    assert "do-not-print-this-secret" not in output
    assert "network: disabled" in output
