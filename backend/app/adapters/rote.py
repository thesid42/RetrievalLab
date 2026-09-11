"""Native Modiqo Rote integration.

Rote exposes a CLI for running an existing Play.  It does not expose a
generic ``lookup`` or ``capture`` HTTP endpoint, so this adapter only invokes
the documented ``rote play run`` command for an explicit Play reference and
keeps capture in the application's durable local mirror.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import sqlite3
import subprocess
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.models import IntegrationStatus, StrategyName, StrategyRun
from app.services.state import StateRepository

MAX_PLAY_STEPS = 32
REPORT_KEYS = frozenset({"result", "run_id", "status", "state", "outcome", "steps", "stages", "summary", "ok"})


@dataclass(frozen=True)
class CLIResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


ProcessRunner = Callable[[Sequence[str], float], Awaitable[CLIResult] | CLIResult]


def _setting(settings: Any, name: str, default: Any = None) -> Any:
    value = getattr(settings, name, default)
    return value if value not in ("", None) else default


async def _default_process_runner(argv: Sequence[str], timeout_seconds: float) -> CLIResult:
    """Run a bounded, argument-vector-only Rote process (never through a shell)."""

    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout_seconds
        )
    except asyncio.CancelledError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.communicate()
        raise
    except TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.communicate()
        raise
    return CLIResult(
        returncode=int(process.returncode or 0),
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )


def _valid_play(play: Any, signature: str) -> dict[str, Any] | None:
    if not isinstance(play, dict) or play.get("query_pattern") != signature:
        return None
    try:
        raw_strategy = play.get("strategy")
        strategy = (
            raw_strategy
            if isinstance(raw_strategy, StrategyName)
            else StrategyName(raw_strategy)
        )
    except (TypeError, ValueError):
        return None
    version = play.get("version")
    steps = play.get("steps")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version < 1
        or not isinstance(steps, list)
        or not steps
        or len(steps) > MAX_PLAY_STEPS
        or any(not isinstance(step, str) or not step.strip() for step in steps)
    ):
        return None
    return {
        "query_pattern": signature,
        "strategy": strategy,
        "version": version,
        "steps": [step.strip() for step in steps],
    }


def _valid_play_ref(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    # Rote supports URI, org/name[@version], local name, and path targets.  We
    # reject option-looking values and NULs; shell=False keeps the remainder a
    # single argv item even when a path contains spaces.
    if not value or len(value) > 2048 or value.startswith("-") or "\x00" in value:
        return None
    return value


def _status(
    mode: str,
    called: bool,
    detail: str,
    *,
    role: str = "muscle-memory replay",
) -> IntegrationStatus:
    return IntegrationStatus(
        name="Modiqo Rote",
        role=role,
        mode=mode,
        called=called,
        detail=detail,
    )


class RotePlaybook:
    """Replay explicit Rote Plays and persist local captures honestly."""

    def __init__(
        self,
        settings: Any,
        state: StateRepository,
        process_runner: ProcessRunner | None = None,
    ):
        self.state = state
        self.cli_path = str(_setting(settings, "rote_cli_path", "rote"))
        self.play_ref = _valid_play_ref(_setting(settings, "rote_play_ref"))
        timeout = float(_setting(settings, "rote_timeout_seconds", 30.0))
        self.timeout_seconds = max(0.1, min(timeout, 120.0))
        self.process_runner = process_runner or _default_process_runner

    async def _run_native_play(
        self,
        play_ref: str | None = None,
        parameters: Mapping[str, str] | None = None,
    ) -> IntegrationStatus:
        if play_ref is not None:
            target = _valid_play_ref(play_ref)
            if target is None:
                return _status(
                    "local-fallback",
                    False,
                    "Rejected invalid Rote Play reference before native replay.",
                )
        else:
            target = self.play_ref
        if target is None:
            return _status(
                "local-fallback",
                False,
                "No explicit Rote Play reference is configured; no native replay was attempted.",
            )
        argv = [self.cli_path, "play", "run", target]
        if parameters:
            if len(parameters) > 32:
                return _status(
                    "local-fallback",
                    False,
                    "Rejected an oversized Rote Play parameter set before native replay.",
                )
            for name, value in parameters.items():
                if (
                    not isinstance(name, str)
                    or not name
                    or name.startswith("-")
                    or "=" in name
                    or not isinstance(value, str)
                    or len(name) > 128
                    or len(value) > 2048
                    or any(ord(char) < 0x20 for char in name + value)
                    or "\x00" in value
                ):
                    return _status(
                        "local-fallback",
                        False,
                        "Rejected invalid Rote Play parameter before native replay.",
                    )
                argv.append(f"{name}={value}")
        # Both flags are documented by Rote: JSON is the canonical machine
        # result and --yes prevents a TTY confirmation from hanging the API.
        argv.extend(["--output=json", "--yes"])
        try:
            raw_result = self.process_runner(argv, self.timeout_seconds)
            if inspect.isawaitable(raw_result):
                raw_result = await raw_result
            if isinstance(raw_result, CLIResult):
                result = raw_result
            elif hasattr(raw_result, "returncode"):
                # Permit subprocess.CompletedProcess and equivalent test
                # doubles while retaining one bounded internal result shape.
                stdout = getattr(raw_result, "stdout", "")
                stderr = getattr(raw_result, "stderr", "")
                if isinstance(stdout, bytes):
                    stdout = stdout.decode("utf-8", errors="replace")
                if isinstance(stderr, bytes):
                    stderr = stderr.decode("utf-8", errors="replace")
                result = CLIResult(int(raw_result.returncode), str(stdout), str(stderr))
            else:
                raise TypeError("Rote process runner returned an invalid result")
        except FileNotFoundError:
            return _status(
                "local-fallback",
                True,
                "Rote CLI is not installed or not on PATH; local play mirror remains authoritative.",
            )
        except TimeoutError:
            return _status(
                "local-fallback",
                True,
                "Rote Play replay timed out; local play mirror remains authoritative.",
            )
        except (OSError, TypeError, ValueError) as error:
            return _status(
                "local-fallback",
                True,
                f"Rote Play replay could not be started; local play mirror remains authoritative ({type(error).__name__}).",
            )
        if result.returncode != 0:
            return _status(
                "local-fallback",
                True,
                f"Rote Play replay failed with exit code {result.returncode}; local play mirror remains authoritative.",
            )
        try:
            report = json.loads(result.stdout)
        except (TypeError, ValueError, json.JSONDecodeError):
            return _status(
                "native-command-completed",
                True,
                "Rote Play command exited 0, but did not return a parseable JSON report; no semantic success was claimed.",
            )
        if not isinstance(report, dict):
            return _status(
                "native-command-completed",
                True,
                "Rote Play command exited 0, but its JSON report was not an object; no semantic success was claimed.",
            )
        if not REPORT_KEYS.intersection(report):
            return _status(
                "native-command-completed",
                True,
                "Rote Play command exited 0, but its JSON object did not match the documented report shape; no semantic success was claimed.",
            )
        return _status(
            "native",
            True,
            "Rote Play command exited 0 with a structured JSON report; its result was not promoted to local retrieval completion.",
        )

    async def replay(
        self,
        play_ref: str | None = None,
        parameters: Mapping[str, str] | None = None,
    ) -> IntegrationStatus:
        """Run a configured Play without inventing lookup/capture subcommands."""

        return await self._run_native_play(play_ref, parameters)

    async def recall(self, query_pattern: str) -> tuple[dict[str, Any] | None, IntegrationStatus]:
        try:
            local_raw = self.state.get_play(query_pattern)
        except (TypeError, ValueError):
            local_raw = None
        local = _valid_play(local_raw, query_pattern)
        detail = (
            "Loaded a validated local play; recall is read-only and native replay is opt-in via replay()."
            if local
            else "No validated local play found; recall is read-only and native replay is opt-in via replay()."
        )
        return local, _status("local-fallback", False, detail)

    async def capture(self, query_pattern: str, winner: StrategyRun) -> IntegrationStatus:
        """Capture only in the local state store.

        Rote's supported capture path starts from a recorded workspace trace and
        crystallizes a pending Play.  There is no safe generic CLI invocation
        that can turn this app's StrategyRun into that trace, so claiming native
        capture here would be false.
        """

        steps = [
            "validate_query_parameters",
            f"execute_{winner.strategy.value}",
            "normalize_candidates",
            "score_evidence",
            "return_top_evidence",
        ]
        try:
            self.state.capture_play(query_pattern, winner.strategy, steps)
        except (OSError, TypeError, ValueError, sqlite3.Error):
            return _status(
                "error-fallback",
                False,
                "Could not persist the validated local play mirror.",
                role="successful workflow capture",
            )
        return _status(
            "local",
            False,
            "Captured a versioned deterministic play in the local StateRepository; Rote native capture requires a recorded workspace trace and was not claimed.",
            role="successful workflow capture",
        )


__all__ = ["CLIResult", "RotePlaybook"]
