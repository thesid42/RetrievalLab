from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from urllib.parse import quote

import httpx

from app.config import Settings
from app.models import (
    Document,
    IntegrationStatus,
    QueryProfile,
    SearchResult,
    StrategyName,
    StrategyRun,
)
from app.services.analyzer import calculate_signals, quality_score
from app.services.query import understand_query
from app.services.retrieval import Corpus
from app.services.security import redact_sensitive
from app.services.text import cosine, hashed_embedding, tokenize

HOTDATA_API_URL = "https://api.hotdata.dev"
MAX_TOP_K = 10
MAX_REMOTE_RESULTS = 100
MAX_QUERY_TERMS = 24
MAX_TERM_LENGTH = 128
MAX_TELEMETRY_FIELDS = 64
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SENSITIVE_TERM = re.compile(r"^(?:sk|api|token|key)(?:[-_]|$)|^[A-Za-z0-9_-]{24,}$", re.IGNORECASE)
_DOCUMENT_COLUMNS = (
    "id",
    "title",
    "content",
    "product",
    "version",
    "published_at",
    "document_type",
    "tags",
)


@dataclass(frozen=True)
class HotdataResponse:
    """Transport result used to separate HTTP success from accepted data."""

    attempted: bool
    called: bool
    detail: str
    data: dict[str, Any] | None = None
    status_code: int | None = None
    remote_mode: str = "remote"


def _clean_setting(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _quote_identifier(identifier: str) -> str:
    """Quote one SQL identifier after validating its shape."""

    if not isinstance(identifier, str) or not _IDENTIFIER.fullmatch(identifier):
        raise ValueError(
            "Hotdata SQL identifiers must contain only letters, digits, and underscores"
        )
    return f'"{identifier}"'


def _qualified_identifier(value: str) -> str:
    """Validate and quote a catalog.schema.table name for HotSQL."""

    parts = value.strip().split(".") if isinstance(value, str) else []
    if len(parts) != 3 or any(not _IDENTIFIER.fullmatch(part) for part in parts):
        raise ValueError("hotdata_table must be a catalog.schema.table identifier")
    return ".".join(_quote_identifier(part) for part in parts)


def _load_table_path(database_id: str, table: str) -> str:
    """Build the documented table-load path without interpolating unsafe paths."""

    if not _PATH_SEGMENT.fullmatch(database_id):
        raise ValueError("Hotdata database id contains an unsafe path character")
    parts = table.strip().split(".") if isinstance(table, str) else []
    if len(parts) == 3:
        catalog, schema, name = parts
        if catalog.lower() != "default":
            raise ValueError("Hotdata loads currently support the default catalog only")
    elif len(parts) == 2:
        schema, name = parts
    else:
        raise ValueError("hotdata telemetry table must be schema.table or default.schema.table")
    if not _IDENTIFIER.fullmatch(schema) or not _IDENTIFIER.fullmatch(name):
        raise ValueError("Hotdata load table identifiers are unsafe")
    return (
        f"/v1/databases/{quote(database_id, safe='')}/schemas/{quote(schema, safe='')}"
        f"/tables/{quote(name, safe='')}/loads"
    )


def _sql_literal(value: str) -> str:
    """Return a safely escaped SQL string literal for a LIKE predicate."""

    if not isinstance(value, str):
        raise TypeError("SQL literal values must be strings")
    escaped = value.replace("\\", "\\\\").replace("'", "''")
    escaped = escaped.replace("%", "\\%").replace("_", "\\_")
    return f"'{escaped}'"


def _candidate_terms(profile: QueryProfile) -> list[str]:
    # The profile can have been built before a caller's query reached this
    # boundary. Re-tokenize the redacted query so API tokens and email addresses
    # never become SQL literals, while preserving exact identifiers such as
    # AUTH-431 from the redacted profile.
    values: list[str] = []
    try:
        safe_profile = understand_query(redact_sensitive(profile.raw_query))
        values.extend(safe_profile.exact_identifiers)
        values.extend(safe_profile.terms)
    except (TypeError, ValueError):
        pass
    # Manually constructed profiles are useful in tests and integrations. Keep
    # their terms only when redaction leaves each value unchanged.
    values.extend(
        value
        for value in [*profile.exact_identifiers, *profile.terms]
        if isinstance(value, str) and _safe_candidate_term(value)
    )
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        value = value.strip()
        if not _safe_candidate_term(value) or len(value) > MAX_TERM_LENGTH:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        terms.append(value)
        if len(terms) >= MAX_QUERY_TERMS:
            break
    return terms


def _safe_candidate_term(value: str) -> bool:
    """Reject credential-shaped literals even if a caller built a profile manually."""

    return (
        bool(value.strip())
        and "@" not in value
        and not _SENSITIVE_TERM.fullmatch(value.strip())
        and redact_sensitive(value) == value
    )


def build_candidate_sql(profile: QueryProfile, table: str, limit: int) -> str:
    """Build a bounded, read-only HotSQL candidate query.

    Hotdata executes the SQL and supplies the candidate rows. The adapter does
    not claim that this predicate is a native vector or full-text search; the
    requested strategy is applied locally to the returned rows.
    """

    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_REMOTE_RESULTS
    ):
        raise ValueError(f"candidate limit must be between 1 and {MAX_REMOTE_RESULTS}")
    quoted_table = _qualified_identifier(table)
    # CSV inference makes version numeric and strips UTC from timestamps.
    # The corpus importer writes UTC; explicitly restore its timezone in SQL.
    fields = ", ".join(
        'CAST("version" AS VARCHAR) AS "version"'
        if field == "version"
        else '("published_at"::TIMESTAMP AT TIME ZONE \'UTC\') AS "published_at"'
        if field == "published_at"
        else _quote_identifier(field)
        for field in _DOCUMENT_COLUMNS
    )
    terms = _candidate_terms(profile)
    searchable = [
        '"id"',
        '"title"',
        '"content"',
        '"product"',
        '"version"',
        '"document_type"',
        '"tags"',
    ]
    if terms:
        predicates = [
            f"LOWER(CAST({field} AS VARCHAR)) LIKE '%' || LOWER({_sql_literal(term)}) || '%' ESCAPE '\\'"
            for term in terms
            for field in searchable
        ]
        where = " OR ".join(predicates)
    else:
        where = "TRUE"
    return (
        f"SELECT {fields} FROM {quoted_table} WHERE ({where}) "
        f"ORDER BY {_quote_identifier('published_at')} DESC, {_quote_identifier('id')} ASC "
        f"LIMIT {limit}"
    )


def _documents_from_query(data: Any) -> list[Document] | None:
    """Validate Hotdata's native ``columns``/``rows`` response shape."""

    if not isinstance(data, dict):
        return None
    columns = data.get("columns")
    rows = data.get("rows")
    truncated = data.get("truncated")
    if truncated is True or (truncated is not None and not isinstance(truncated, bool)):
        # A preview is not a complete candidate set. We do not claim retrieval
        # success when the result requires a second, unimplemented Results API call.
        return None
    if (
        not isinstance(columns, list)
        or not columns
        or not all(isinstance(item, str) for item in columns)
    ):
        return None
    normalized_columns = [column.strip().lower() for column in columns]
    if any(not column or normalized_columns.count(column) > 1 for column in normalized_columns):
        return None
    required = set(_DOCUMENT_COLUMNS)
    if not required.issubset(normalized_columns) or not isinstance(rows, list):
        return None
    if len(rows) > MAX_REMOTE_RESULTS:
        return None
    total_row_count = data.get("total_row_count")
    if (
        isinstance(total_row_count, bool)
        or not isinstance(total_row_count, (int, type(None)))
        or (isinstance(total_row_count, int) and total_row_count != len(rows))
    ):
        return None
    for count_key in ("preview_row_count", "row_count"):
        count = data.get(count_key)
        if count is not None and (
            isinstance(count, bool) or not isinstance(count, int) or count != len(rows)
        ):
            return None
    nullable = data.get("nullable")
    if nullable is not None and (
        not isinstance(nullable, list)
        or len(nullable) != len(columns)
        or any(not isinstance(value, bool) for value in nullable)
    ):
        return None

    documents: list[Document] = []
    seen_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns):
            return None
        mapped = dict(zip(normalized_columns, row, strict=True))
        tags = mapped.get("tags")
        if tags is None:
            mapped["tags"] = []
        elif isinstance(tags, str):
            try:
                parsed_tags = json.loads(tags)
            except (TypeError, ValueError):
                return None
            if not isinstance(parsed_tags, list):
                return None
            mapped["tags"] = parsed_tags
        try:
            document = Document.model_validate(
                {field: mapped[field] for field in _DOCUMENT_COLUMNS}
            )
        except (TypeError, ValueError):
            return None
        if document.id in seen_ids:
            return None
        seen_ids.add(document.id)
        documents.append(document)
    return documents


def _rank_remote_documents(
    profile: QueryProfile, documents: list[Document], strategy: StrategyName, top_k: int
) -> list[SearchResult]:
    """Apply the requested strategy to only the documents returned by Hotdata."""

    if not documents:
        return []
    query_terms = tokenize(profile.raw_query, remove_stop_words=False)
    tokens = {
        document.id: tokenize(
            f"{document.id} {document.title} {document.content} {document.product} "
            f"{document.document_type} {' '.join(document.tags)}",
            remove_stop_words=False,
        )
        for document in documents
    }
    lengths = [len(tokens[document.id]) for document in documents]
    average_length = sum(lengths) / len(lengths) if lengths else 1.0
    dense_query = hashed_embedding(profile.raw_query)
    dense_raw = {
        document.id: max(0.0, cosine(dense_query, hashed_embedding(" ".join(tokens[document.id]))))
        for document in documents
    }
    dense_max = max(dense_raw.values(), default=1.0)
    dense = {key: value / dense_max if dense_max else 0.0 for key, value in dense_raw.items()}
    lexical_raw: dict[str, float] = {}
    for document in documents:
        document_tokens = tokens[document.id]
        counts = {term: document_tokens.count(term) for term in query_terms}
        score = 0.0
        for term in query_terms:
            frequency = counts[term]
            containing = sum(term in tokens[item.id] for item in documents)
            inverse_frequency = math.log(
                1 + (len(documents) - containing + 0.5) / (containing + 0.5)
            )
            denominator = frequency + 1.5 * (
                1 - 0.75 + 0.75 * len(document_tokens) / average_length
            )
            score += inverse_frequency * (frequency * 2.5 / denominator if denominator else 0)
        lexical_raw[document.id] = score
    lexical_max = max(lexical_raw.values(), default=1.0)
    lexical = {
        key: value / lexical_max if lexical_max else 0.0 for key, value in lexical_raw.items()
    }

    newest = max(document.published_at for document in documents)
    scored: list[tuple[Document, float, list[str]]] = []
    for document in documents:
        reasons: list[str] = []
        if strategy is StrategyName.DENSE:
            score = dense[document.id]
            reasons.append("semantic similarity over Hotdata candidates")
        elif strategy is StrategyName.BM25:
            score = lexical[document.id]
            reasons.append("local lexical ranking over Hotdata candidates")
        else:
            score = 0.58 * lexical[document.id] + 0.42 * dense[document.id]
            reasons.extend(["local lexical ranking", "local semantic ranking"])
        age_days = max(0, (newest - document.published_at).days)
        freshness = math.exp(-age_days / 730)
        if strategy is StrategyName.FRESHNESS:
            score = 0.50 * lexical[document.id] + 0.25 * dense[document.id] + 0.25 * freshness
            reasons.append("freshness boost over Hotdata candidates")
        elif strategy is StrategyName.HYBRID_RERANK:
            identifier_hit = any(
                identifier.lower() in tokens[document.id]
                for identifier in profile.exact_identifiers
            )
            score += 0.20 if identifier_hit else 0
            score += 0.12 * freshness if profile.current_intent else 0
            reasons.append("intent-aware local rerank over Hotdata candidates")
        scored.append((document, score, reasons))
    scored.sort(key=lambda item: (item[1], item[0].published_at, item[0].id), reverse=True)
    maximum = scored[0][1] if scored and scored[0][1] else 1.0
    return [
        SearchResult(
            document=document,
            score=round(max(0.0, min(1.0, score / maximum)), 4),
            rank=index,
            strategy=strategy,
            reasons=reasons,
        )
        for index, (document, score, reasons) in enumerate(scored[:top_k], start=1)
    ]


class HotdataNativeClient:
    """Small native HTTP client for Hotdata's documented SQL/load endpoints."""

    def __init__(
        self,
        api_url: str | None,
        api_key: str | None,
        workspace_id: str | None,
        database_id: str | None,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.api_url = (_clean_setting(api_url) or HOTDATA_API_URL).rstrip("/")
        self.api_key = _clean_setting(api_key)
        self.workspace_id = _clean_setting(workspace_id)
        self.database_id = _clean_setting(database_id)
        self.timeout = timeout
        self.transport = transport

    def _headers(self, *, include_database: bool = True) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.workspace_id:
            headers["X-Workspace-Id"] = self.workspace_id
        if include_database and self.database_id:
            headers["X-Database-Id"] = self.database_id
        return headers

    def _configured(self) -> bool:
        return bool(self.api_key and self.workspace_id and self.database_id)

    def _client_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"timeout": self.timeout}
        if self.transport is not None:
            kwargs["transport"] = self.transport
        return kwargs

    async def query(self, sql: str) -> HotdataResponse:
        if not self._configured():
            return HotdataResponse(
                attempted=False,
                called=False,
                detail="Hotdata native query is not configured; local corpus executed.",
            )
        try:
            async with httpx.AsyncClient(**self._client_kwargs()) as client:
                response = await client.post(
                    f"{self.api_url}/v1/query",
                    json={"sql": sql},
                    headers=self._headers(),
                )
                response.raise_for_status()
                if not response.content:
                    return HotdataResponse(
                        attempted=True,
                        called=False,
                        detail="Hotdata query returned no JSON response; local corpus executed.",
                        status_code=response.status_code,
                    )
                data = response.json()
        except (httpx.HTTPError, TypeError, ValueError) as error:
            return HotdataResponse(
                attempted=True,
                called=False,
                detail=f"Hotdata query unavailable or invalid ({type(error).__name__}); local corpus executed.",
            )
        if not isinstance(data, dict):
            return HotdataResponse(
                attempted=True,
                called=False,
                detail="Hotdata query returned a JSON value instead of an object; local corpus executed.",
                status_code=response.status_code,
            )
        return HotdataResponse(
            attempted=True,
            called=True,
            detail="Hotdata native SQL query returned a JSON result.",
            data=data,
            status_code=response.status_code,
        )

    @staticmethod
    def _load_acknowledged(status_code: int, data: dict[str, Any] | None) -> tuple[bool, str]:
        """Validate the documented synchronous or submitted load response."""

        if not isinstance(data, dict):
            return (
                False,
                "Hotdata load returned no documented acknowledgement; telemetry remains local.",
            )
        if status_code == 200:
            required = {
                "arrow_schema_json",
                "connection_id",
                "row_count",
                "schema_name",
                "table_name",
            }
            row_count = data.get("row_count")
            valid = (
                required.issubset(data)
                and isinstance(data["arrow_schema_json"], str)
                and bool(data["arrow_schema_json"].strip())
                and all(
                    isinstance(data[key], str) and data[key].strip()
                    for key in ("connection_id", "schema_name", "table_name")
                )
                and isinstance(row_count, int)
                and not isinstance(row_count, bool)
                and row_count >= 0
            )
            return (
                valid,
                "Hotdata completed the documented table load."
                if valid
                else "Hotdata load response was missing its completed table acknowledgement; telemetry remains local.",
            )
        if status_code == 202:
            required = {"id", "status", "status_url"}
            valid = (
                required.issubset(data)
                and all(isinstance(data[key], str) and data[key].strip() for key in required)
                and (
                    data["status_url"].startswith("/") or data["status_url"].startswith("https://")
                )
            )
            return (
                valid,
                "Hotdata submitted the documented table load for background processing."
                if valid
                else "Hotdata load response was missing its submitted-job acknowledgement; telemetry remains local.",
            )
        return (
            False,
            "Hotdata load returned an unsupported success status; telemetry remains local.",
        )

    async def load_csv(
        self,
        table: str,
        csv_data: str,
        idempotency_key: str,
        *,
        mode: str,
    ) -> HotdataResponse:
        if not self._configured():
            return HotdataResponse(
                attempted=False,
                called=False,
                detail="Hotdata table load is not configured; no remote write was attempted.",
            )
        if mode not in {"append", "replace"}:
            return HotdataResponse(
                attempted=False,
                called=False,
                detail="Hotdata table load mode is unsupported; no remote write was attempted.",
            )
        try:
            path = _load_table_path(self.database_id or "", table)
        except ValueError as error:
            return HotdataResponse(
                attempted=False,
                called=False,
                detail=f"Hotdata table is invalid ({error}); no remote write was attempted.",
            )
        body = {
            "mode": mode,
            "data": csv_data,
            "format": "csv",
            "idempotency_key": idempotency_key,
        }
        try:
            async with httpx.AsyncClient(**self._client_kwargs()) as client:
                response = await client.post(
                    f"{self.api_url}{path}",
                    json=body,
                    headers=self._headers(),
                )
                response.raise_for_status()
                data: dict[str, Any] | None = None
                if response.content:
                    candidate = response.json()
                    if isinstance(candidate, dict):
                        data = candidate
                    else:
                        return HotdataResponse(
                            attempted=True,
                            called=False,
                            detail="Hotdata load returned a JSON value instead of an object; no acknowledgement was accepted.",
                            status_code=response.status_code,
                        )
        except (httpx.HTTPError, TypeError, ValueError) as error:
            return HotdataResponse(
                attempted=True,
                called=False,
                detail=f"Hotdata table load failed ({type(error).__name__}); no acknowledgement was accepted.",
            )
        acknowledged, detail = self._load_acknowledged(response.status_code, data)
        return HotdataResponse(
            attempted=True,
            called=acknowledged,
            detail=detail,
            data=data,
            status_code=response.status_code,
            remote_mode="remote-submitted" if response.status_code == 202 else "remote",
        )

    async def load_table(self, table: str, csv_data: str, idempotency_key: str) -> HotdataResponse:
        return await self.load_csv(table, csv_data, idempotency_key, mode="append")


NativeHotdataClient = HotdataNativeClient


def _telemetry_csv(payload: dict[str, Any]) -> tuple[str, str] | None:
    if not payload or len(payload) > MAX_TELEMETRY_FIELDS:
        return None
    fields = sorted(key for key in payload if isinstance(key, str) and key.strip())
    if len(fields) != len(payload) or len(fields) > MAX_TELEMETRY_FIELDS:
        return None
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(fields)
    values: list[str] = []
    for field in fields:
        value = payload[field]
        if isinstance(value, (dict, list, tuple)):
            values.append(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str))
        elif value is None:
            values.append("")
        else:
            values.append(str(value))
    writer.writerow(values)
    idempotency_key = hashlib.sha256(output.getvalue().encode("utf-8")).hexdigest()[:32]
    return output.getvalue(), idempotency_key


def _status(
    remote: HotdataResponse,
    *,
    role: str,
    accepted: bool,
    accepted_detail: str,
    fallback_detail: str,
) -> IntegrationStatus:
    if remote.attempted and remote.called and accepted:
        return IntegrationStatus(
            name="hotdata.dev",
            role=role,
            mode="remote+local-ranking"
            if role == "SQL candidate retrieval"
            else remote.remote_mode,
            called=True,
            detail=accepted_detail,
        )
    detail = fallback_detail
    if remote.detail:
        detail = f"{detail} {remote.detail}"
    return IntegrationStatus(
        name="hotdata.dev",
        role=role,
        mode="local-fallback",
        called=remote.attempted,
        detail=detail,
    )


class HotdataQueryEngine:
    def __init__(
        self,
        settings: Settings,
        corpus: Corpus,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.settings = settings
        self.corpus = corpus
        api_url = getattr(settings, "hotdata_api_url", HOTDATA_API_URL)
        self.client = HotdataNativeClient(
            api_url,
            getattr(settings, "hotdata_api_key", None),
            getattr(settings, "hotdata_workspace_id", None),
            getattr(settings, "hotdata_database_id", None),
            getattr(settings, "request_timeout_seconds", 12.0),
            transport=transport,
        )

    @property
    def remote(self) -> HotdataNativeClient:
        return self.client

    @remote.setter
    def remote(self, value: HotdataNativeClient) -> None:
        self.client = value

    async def execute(
        self, profile: QueryProfile, strategy: StrategyName, top_k: int
    ) -> tuple[StrategyRun, IntegrationStatus]:
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= MAX_TOP_K:
            raise ValueError(f"top_k must be an integer between 1 and {MAX_TOP_K}")
        try:
            normalized_strategy = (
                strategy if isinstance(strategy, StrategyName) else StrategyName(strategy)
            )
        except (TypeError, ValueError) as error:
            raise ValueError("strategy must be a supported StrategyName") from error
        started = perf_counter()
        table = getattr(self.settings, "hotdata_table", "default.main.retrieval_documents")
        candidate_limit = min(MAX_REMOTE_RESULTS, max(top_k, top_k * 5))
        try:
            sql = build_candidate_sql(profile, table, candidate_limit)
        except (TypeError, ValueError) as error:
            remote = HotdataResponse(
                attempted=False,
                called=False,
                detail=f"Hotdata table configuration is invalid ({error}); local corpus executed.",
            )
            documents = None
        else:
            remote = await self.client.query(sql)
            documents = _documents_from_query(remote.data) if remote.called else None

        accepted_remote = documents is not None
        if accepted_remote:
            results = _rank_remote_documents(profile, documents, normalized_strategy, top_k)
        else:
            try:
                results = self.corpus.search(profile, normalized_strategy, top_k)
            except (ValueError, ZeroDivisionError):
                results = []
        signals = calculate_signals(profile, results)
        run = StrategyRun(
            strategy=normalized_strategy,
            results=results,
            quality_score=quality_score(profile, signals),
            latency_ms=round((perf_counter() - started) * 1000, 2),
            signals=signals,
        )
        status = _status(
            remote,
            role="SQL candidate retrieval",
            accepted=accepted_remote,
            accepted_detail=(
                "Hotdata SQL supplied grounded candidates; the requested strategy ranked those rows locally."
                if results
                else "Hotdata SQL supplied an explicit empty candidate set; no local candidates were substituted."
            ),
            fallback_detail=(
                "Executed the requested strategy against the local corpus because native Hotdata candidates were unavailable or failed validation."
            ),
        )
        return run, status

    async def record_telemetry(self, payload: dict) -> IntegrationStatus:
        telemetry_table = getattr(self.settings, "hotdata_telemetry_table", None)
        encoded = _telemetry_csv(payload) if isinstance(payload, dict) else None
        if not telemetry_table or encoded is None:
            return IntegrationStatus(
                name="hotdata.dev",
                role="retrieval telemetry",
                mode="local-fallback",
                called=False,
                detail="Telemetry retained in the local run store; no Hotdata telemetry table is configured.",
            )
        csv_data, idempotency_key = encoded
        remote = await self.client.load_table(telemetry_table, csv_data, idempotency_key)
        return _status(
            remote,
            role="retrieval telemetry",
            accepted=remote.called,
            accepted_detail=remote.detail,
            fallback_detail="Telemetry retained in the local run store; the native table load was not accepted.",
        )
