"""Configuration regressions; provider wire contracts live in test_*_native.py."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import PROJECT_ROOT, Settings
from app.services.integration_setup import deprecated_environment_names, integration_readiness


def test_native_hosts_and_blank_secrets():
    settings = Settings(_env_file=None, hotdata_api_key="  ", cognee_api_key=" ")
    assert settings.hotdata_api_url == "https://api.hotdata.dev"
    assert settings.hydradb_api_url == "https://api.hydradb.com"
    assert settings.rocketride_uri == "https://api.rocketride.ai"
    assert settings.cognee_api_url is None
    assert settings.hotdata_api_key is None and settings.cognee_api_key is None


def test_native_environment_aliases_and_explicit_settings(monkeypatch):
    monkeypatch.setenv("HOTDATA_API_KEY", "native-test-secret")
    monkeypatch.setenv("HYDRA_DB_API_KEY", "hydra-test-secret")
    monkeypatch.setenv("ROCKETRIDE_APIKEY", "rocket-test-secret")
    assert Settings(_env_file=None).hotdata_api_key == "native-test-secret"
    assert Settings(_env_file=None).hydradb_api_key == "hydra-test-secret"
    assert Settings(_env_file=None).rocketride_api_key == "rocket-test-secret"
    assert Settings(_env_file=None, hotdata_api_key=None).hotdata_api_key is None
    monkeypatch.setenv("RETRIEVALLAB_HOTDATA_API_KEY", "app-test-secret")
    assert Settings(_env_file=None).hotdata_api_key == "app-test-secret"


def test_readiness_never_exposes_secrets():
    settings = Settings(_env_file=None, hotdata_api_key="DO-NOT-PRINT", cognee_api_key="PRIVATE")
    report = json.dumps(integration_readiness(settings))
    assert "DO-NOT-PRINT" not in report and "PRIVATE" not in report
    assert "DO-NOT-PRINT" not in repr(settings) and "PRIVATE" not in repr(settings)
    assert all(not entry["live_verified"] for entry in integration_readiness(settings))
    assert "RETRIEVALLAB_HOTDATA_WORKSPACE_ID" in report


@pytest.mark.parametrize("url", [
    "dashboard.example", "https://secret@example.test", "https://example.test?token=secret",
    "http://example.test", "https://example.test/#secret", "file:///tmp/a",
])
def test_provider_urls_reject_insecure_or_embedded_credentials(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, hotdata_api_url=url)


def test_local_provider_and_path_resolution():
    settings = Settings(_env_file=None, cognee_api_url="http://localhost:8001/",
                        rocketride_pipeline_path="backend/pipelines/retrieval.pipe")
    assert settings.cognee_api_url == "http://localhost:8001"
    assert settings.rocketride_pipeline_path == PROJECT_ROOT / "backend/pipelines/retrieval.pipe"
    assert all(Path(path).is_absolute() for path in Settings.model_config["env_file"])
    assert Settings(_env_file=None, rocketride_uri="ws://localhost:5565").rocketride_uri.endswith("5565")
    assert Settings(_env_file=None, rocketride_uri="wss://runtime.example").rocketride_uri.startswith("wss:")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, rocketride_uri="ws://runtime.example")


def test_deprecated_names_reported_without_values(tmp_path):
    env = tmp_path / ".env"
    env.write_text("RETRIEVALLAB_HOTDATA_BASE_URL=https://old.test\nIGNORED=secret\n")
    assert deprecated_environment_names((env,), {"RETRIEVALLAB_ROTE_API_KEY": "private"}) == [
        "RETRIEVALLAB_HOTDATA_BASE_URL", "RETRIEVALLAB_ROTE_API_KEY",
    ]
