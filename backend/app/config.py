from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).parents[2]


class Settings(BaseSettings):
    app_name: str = "RetrievalLab"
    environment: str = "development"
    # Demo fault injection is deliberately opt-in. Production must never run it.
    demo_mode: bool = False
    cors_origins: str = "http://localhost:5173"
    api_access_key: str | None = None
    corpus_path: Path = Path(__file__).parent / "data" / "corpus.json"
    # Keep the durable store at the repository-level runtime/ directory, regardless
    # of the process working directory (the documented location for the demo).
    state_path: Path = PROJECT_ROOT / "runtime" / "retrievallab.db"

    cognee_base_url: str | None = None
    cognee_api_key: str | None = None
    hydradb_base_url: str | None = None
    hydradb_api_key: str | None = None
    hotdata_base_url: str | None = None
    hotdata_api_key: str | None = None
    rocketride_base_url: str | None = None
    rocketride_api_key: str | None = None
    rote_base_url: str | None = None
    rote_api_key: str | None = None

    request_timeout_seconds: float = 12.0
    baseline_top_k: int = 5
    strategy_top_k: int = 5
    memory_similarity_threshold: float = 0.58
    max_concurrent_runs: int = 8

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_prefix="RETRIEVALLAB_",
        extra="ignore",
    )

    @field_validator("corpus_path", "state_path", mode="before")
    @classmethod
    def resolve_path(cls, value: Path | str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @field_validator("api_access_key", mode="before")
    @classmethod
    def blank_key_is_missing(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("request_timeout_seconds")
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
