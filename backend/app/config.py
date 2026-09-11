from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).parents[2]


def provider_field(name: str, *aliases: str, default=None, secret: bool = False):
    return Field(
        default=default,
        validation_alias=AliasChoices(f"RETRIEVALLAB_{name.upper()}", *aliases),
        repr=not secret,
    )


class Settings(BaseSettings):
    app_name: str = "RetrievalLab"
    environment: str = "development"
    # Demo fault injection is deliberately opt-in. Production must never run it.
    demo_mode: bool = False
    cors_origins: str = "http://localhost:5173"
    api_access_key: str | None = Field(default=None, repr=False)
    corpus_path: Path = Path(__file__).parent / "data" / "corpus.json"
    # Keep the durable store at the repository-level runtime/ directory, regardless
    # of the process working directory (the documented location for the demo).
    state_path: Path = PROJECT_ROOT / "runtime" / "retrievallab.db"

    # Native provider settings. Missing credentials keep the local fallback active.
    cognee_api_url: str | None = provider_field("cognee_api_url", "COGNEE_SERVICE_URL")
    cognee_api_key: str | None = provider_field("cognee_api_key", "COGNEE_API_KEY", secret=True)
    cognee_auth_mode: Literal["api_key", "bearer"] = "api_key"
    cognee_dataset: str = "retrievallab"
    hydradb_api_url: str = provider_field(
        "hydradb_api_url", "HYDRADB_API_URL", "HYDRADB_BASE_URL", default="https://api.hydradb.com"
    )
    hydradb_api_key: str | None = provider_field(
        "hydradb_api_key", "HYDRA_DB_API_KEY", "HYDRADB_API_KEY", secret=True
    )
    hydradb_tenant_id: str | None = provider_field(
        "hydradb_tenant_id", "HYDRADB_DATABASE", "HYDRADB_TENANT_ID"
    )
    hydradb_sub_tenant_id: str | None = provider_field(
        "hydradb_sub_tenant_id", "HYDRADB_COLLECTION", "HYDRADB_SUB_TENANT_ID"
    )
    hotdata_api_url: str = provider_field(
        "hotdata_api_url", "HOTDATA_API_URL", default="https://api.hotdata.dev"
    )
    hotdata_api_key: str | None = provider_field("hotdata_api_key", "HOTDATA_API_KEY", secret=True)
    hotdata_workspace_id: str | None = provider_field(
        "hotdata_workspace_id", "HOTDATA_WORKSPACE_ID"
    )
    hotdata_database_id: str | None = provider_field("hotdata_database_id", "HOTDATA_DATABASE_ID")
    hotdata_table: str = "default.main.retrieval_documents"
    hotdata_telemetry_table: str | None = None
    rocketride_uri: str = provider_field(
        "rocketride_uri", "ROCKETRIDE_URI", default="https://api.rocketride.ai"
    )
    rocketride_api_key: str | None = provider_field(
        "rocketride_api_key", "ROCKETRIDE_APIKEY", "ROCKETRIDE_AUTH", secret=True
    )
    rocketride_pipeline_path: Path | None = None
    rocketride_source_id: str | None = None
    rote_cli_path: str = "rote"
    rote_wsl_distribution: str | None = None
    rote_python_path: str | None = None
    rote_play_ref: str | None = None
    rote_timeout_seconds: float = 30.0

    request_timeout_seconds: float = 12.0
    baseline_top_k: int = 5
    strategy_top_k: int = 5
    memory_similarity_threshold: float = 0.58
    max_concurrent_runs: int = 8

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env"),
        env_prefix="RETRIEVALLAB_",
        extra="ignore",
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    @field_validator("corpus_path", "state_path", "rocketride_pipeline_path", mode="before")
    @classmethod
    def resolve_path(cls, value: Path | str | None) -> Path | None:
        if value is None or value == "":
            return None
        path = Path(value)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @field_validator(
        "api_access_key",
        "cognee_api_url",
        "cognee_api_key",
        "hydradb_api_key",
        "hydradb_tenant_id",
        "hydradb_sub_tenant_id",
        "hotdata_api_key",
        "hotdata_workspace_id",
        "hotdata_database_id",
        "hotdata_telemetry_table",
        "rocketride_api_key",
        "rocketride_source_id",
        "rote_play_ref",
        mode="before",
    )
    @classmethod
    def blank_key_is_missing(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("cognee_api_url", "hydradb_api_url", "hotdata_api_url", "rocketride_uri")
    @classmethod
    def valid_provider_url(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        schemes = (
            {"http", "https", "ws", "wss"}
            if info.field_name == "rocketride_uri"
            else {"http", "https"}
        )
        if (
            parsed.scheme not in schemes
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "provider URL must use a supported scheme without credentials/query/fragment"
            )
        if parsed.scheme in {"http", "ws"} and parsed.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError(
                "remote provider URLs require HTTPS; HTTP is allowed only for loopback"
            )
        return value

    @field_validator("request_timeout_seconds", "rote_timeout_seconds")
    @classmethod
    def valid_timeout(cls, value: float) -> float:
        if not 0 < value <= 120:
            raise ValueError("request_timeout_seconds must be between 0 and 120")
        return value

    @field_validator("memory_similarity_threshold")
    @classmethod
    def valid_similarity_threshold(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("memory_similarity_threshold must be between 0 and 1")
        return value

    @field_validator("max_concurrent_runs")
    @classmethod
    def valid_concurrency(cls, value: int) -> int:
        if not 1 <= value <= 128:
            raise ValueError("max_concurrent_runs must be between 1 and 128")
        return value

    @model_validator(mode="after")
    def production_safety(self) -> "Settings":
        if self.environment.lower() == "production":
            if self.demo_mode:
                raise ValueError("demo_mode must be false in production")
            if not self.api_access_key:
                raise ValueError("api_access_key is required in production")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
