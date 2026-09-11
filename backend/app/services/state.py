from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.models import FailureType, MemoryMatch, StrategyName, utc_now


class StateRepository:
    """Durable local substrate used in demo mode and mirrored by remote adapters."""

    def __init__(self, path: Path, *, corpus_version: str = "unknown"):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.corpus_version = corpus_version or "unknown"
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    query_pattern TEXT NOT NULL,
                    failure_type TEXT NOT NULL,
                    winning_strategy TEXT NOT NULL,
                    useful_document_ids TEXT NOT NULL,
                    successful_runs INTEGER NOT NULL DEFAULT 1,
                    payload TEXT NOT NULL,
                    corpus_version TEXT NOT NULL DEFAULT 'unknown',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS plays (
                    query_pattern TEXT PRIMARY KEY,
                    strategy TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    steps TEXT NOT NULL,
                    replay_count INTEGER NOT NULL DEFAULT 0,
                    corpus_version TEXT NOT NULL DEFAULT 'unknown',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    query_pattern TEXT NOT NULL,
                    path TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    quality REAL NOT NULL,
                    attempts INTEGER NOT NULL,
                    planner_calls INTEGER NOT NULL,
                    elapsed_ms REAL NOT NULL,
                    outcome TEXT NOT NULL DEFAULT 'degraded',
                    baseline_quality REAL,
                    quality_lift REAL,
                    memory_promoted INTEGER NOT NULL DEFAULT 0,
                    play_captured INTEGER NOT NULL DEFAULT 0,
                    replay_attempted INTEGER NOT NULL DEFAULT 0,
                    memory_hit INTEGER NOT NULL DEFAULT 0,
                    corpus_version TEXT NOT NULL DEFAULT 'unknown',
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(connection, "memories", "corpus_version", "TEXT NOT NULL DEFAULT 'unknown'")
            self._ensure_column(connection, "plays", "corpus_version", "TEXT NOT NULL DEFAULT 'unknown'")
            for name, definition in (
                ("outcome", "TEXT NOT NULL DEFAULT 'degraded'"),
                ("baseline_quality", "REAL"),
                ("quality_lift", "REAL"),
                ("memory_promoted", "INTEGER NOT NULL DEFAULT 0"),
                ("play_captured", "INTEGER NOT NULL DEFAULT 0"),
                ("replay_attempted", "INTEGER NOT NULL DEFAULT 0"),
                ("memory_hit", "INTEGER NOT NULL DEFAULT 0"),
                ("corpus_version", "TEXT NOT NULL DEFAULT 'unknown'"),
            ):
                self._ensure_column(connection, "runs", name, definition)

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table: str, name: str, definition: str) -> None:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
        if name not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def find_memory(self, query_pattern: str) -> MemoryMatch | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE query_pattern = ? AND corpus_version = ? "
                "ORDER BY successful_runs DESC LIMIT 1",
                (query_pattern, self.corpus_version),
            ).fetchone()
        if not row:
            return None
        try:
            return MemoryMatch(
                memory_id=row["id"], query_pattern=row["query_pattern"],
                failure_type=FailureType(row["failure_type"]),
                winning_strategy=StrategyName(row["winning_strategy"]),
                # Local lookup is an exact signature match, so report the measured
                # identity match rather than an invented approximate score.
                similarity=1.0, successful_runs=row["successful_runs"],
            )
        except (ValueError, TypeError):
            return None

    def upsert_memory(self, payload: dict[str, Any]) -> None:
        now = utc_now().isoformat()
        corpus_version = payload.get("corpus_version", self.corpus_version)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memories (
                    id, query_pattern, failure_type, winning_strategy, useful_document_ids,
                    successful_runs, payload, corpus_version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    query_pattern = excluded.query_pattern,
                    failure_type = excluded.failure_type,
                    winning_strategy = excluded.winning_strategy,
                    useful_document_ids = excluded.useful_document_ids,
                    successful_runs = memories.successful_runs + 1,
                    payload = excluded.payload,
                    corpus_version = excluded.corpus_version,
                    updated_at = excluded.updated_at
                """,
                (
                    payload["memory_id"], payload["query_pattern"], payload["failure_type"],
                    payload["winning_strategy"], json.dumps(payload["useful_document_ids"]),
                    json.dumps({**payload, "corpus_version": corpus_version}), corpus_version,
                    now, now,
                ),
            )

    def capture_play(self, query_pattern: str, strategy: StrategyName, steps: list[str]) -> None:
        now = utc_now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO plays (
                    query_pattern, strategy, version, steps, replay_count, corpus_version, updated_at
                ) VALUES (?, ?, 1, ?, 0, ?, ?)
                ON CONFLICT(query_pattern) DO UPDATE SET
                    strategy = excluded.strategy, version = plays.version + 1,
                    steps = excluded.steps, corpus_version = excluded.corpus_version,
                    updated_at = excluded.updated_at
                """,
                (query_pattern, strategy.value, json.dumps(steps), self.corpus_version, now),
            )

    def get_play(self, query_pattern: str) -> dict[str, Any] | None:
        """Read a play without mutating replay telemetry."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM plays WHERE query_pattern = ? AND corpus_version = ?",
                (query_pattern, self.corpus_version),
            ).fetchone()
        if not row:
            return None
        try:
            strategy = StrategyName(row["strategy"])
            steps = json.loads(row["steps"])
            if not isinstance(steps, list) or not all(isinstance(step, str) for step in steps):
                return None
        except (ValueError, TypeError, json.JSONDecodeError):
            return None
        return {
            "query_pattern": row["query_pattern"], "strategy": strategy,
            "version": row["version"], "steps": steps, "replay_count": row["replay_count"],
        }

    def record_replay(self, query_pattern: str) -> None:
        """Record one replay after the saved play has actually executed."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE plays SET replay_count = replay_count + 1 "
                "WHERE query_pattern = ? AND corpus_version = ?",
                (query_pattern, self.corpus_version),
            )

    def save_run(self, payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO runs (
                    id, query, query_pattern, path, strategy, quality, attempts,
                    planner_calls, elapsed_ms, outcome, baseline_quality, quality_lift,
                    memory_promoted, play_captured, replay_attempted, memory_hit,
                    corpus_version, payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["run_id"], payload["query"], payload["query_pattern"], payload["path"],
                    payload["strategy"], payload["quality"], payload["attempts"],
                    payload["planner_calls"], payload["elapsed_ms"], payload.get("outcome", "degraded"),
                    payload.get("baseline_quality"), payload.get("quality_lift"),
                    int(payload.get("memory_promoted", False)), int(payload.get("play_captured", False)),
                    int(payload.get("replay_attempted", False)), int(payload.get("memory_hit", False)),
                    payload.get("corpus_version", self.corpus_version), json.dumps(payload),
                    payload.get("created_at", utc_now().isoformat()),
                ),
            )

    def dashboard(self) -> dict[str, Any]:
        with self._connect() as connection:
            aggregate = connection.execute(
                """
                SELECT COUNT(*) total,
                    SUM(CASE WHEN path = 'discovery' THEN 1 ELSE 0 END) discovery,
                    SUM(CASE WHEN path = 'replay' THEN 1 ELSE 0 END) replay,
                    AVG(CASE WHEN path = 'discovery' THEN attempts END) discovery_attempts,
                    AVG(CASE WHEN path = 'replay' THEN attempts END) replay_attempts,
                    AVG(quality_lift) average_quality_lift
                FROM runs WHERE corpus_version = ?
                """, (self.corpus_version,),
            ).fetchone()
            recent = connection.execute(
                """SELECT id, query, path, strategy, quality, attempts, elapsed_ms,
                          outcome, memory_promoted, play_captured, replay_attempted, created_at
                   FROM runs WHERE corpus_version = ? ORDER BY created_at DESC LIMIT 10""",
                (self.corpus_version,),
            ).fetchall()
            patterns_learned = connection.execute(
                "SELECT COUNT(*) FROM memories WHERE corpus_version = ?", (self.corpus_version,)
            ).fetchone()[0]
            history = connection.execute(
                "SELECT id, quality, baseline_quality, created_at FROM runs "
                "WHERE corpus_version = ? ORDER BY created_at ASC LIMIT 100",
                (self.corpus_version,),
            ).fetchall()
            discovery_latency = connection.execute(
                "SELECT AVG(elapsed_ms) FROM runs WHERE path = 'discovery' AND corpus_version = ?",
                (self.corpus_version,),
            ).fetchone()[0]
            replay_latency = connection.execute(
                "SELECT AVG(elapsed_ms) FROM runs WHERE path = 'replay' AND corpus_version = ?",
                (self.corpus_version,),
            ).fetchone()[0]

        total = aggregate["total"] or 0
        replay = aggregate["replay"] or 0
        discovery_attempts = aggregate["discovery_attempts"]
        replay_attempts = aggregate["replay_attempts"]

        def savings(discovery: float | None, replay_value: float | None) -> float | None:
            if discovery is None or replay_value is None or discovery <= 0:
                return None
            return round((discovery - replay_value) / discovery * 100, 2)

        return {
            "total_runs": total, "discovery_runs": aggregate["discovery"] or 0,
            "replay_runs": replay, "patterns_learned": patterns_learned,
            "memory_hit_rate": round(replay / total, 4) if total else 0,
            "average_attempts_discovery": round(discovery_attempts or 0, 2),
            "average_attempts_replay": round(replay_attempts or 0, 2),
            "average_quality_lift": (
                round(aggregate["average_quality_lift"], 4)
                if aggregate["average_quality_lift"] is not None else None
            ),
            "attempts_saved_percent": savings(discovery_attempts, replay_attempts),
            "latency_saved_percent": savings(discovery_latency, replay_latency),
            "quality_history": [
                {"id": row["id"], "quality": row["quality"],
                 "baseline_quality": row["baseline_quality"], "created_at": row["created_at"]}
                for row in history
            ],
            "recent_runs": [dict(row) for row in recent],
        }
