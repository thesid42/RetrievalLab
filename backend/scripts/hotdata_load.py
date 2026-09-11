"""Explicit, dry-run-first loader for the RetrievalLab corpus.

The script only targets Hotdata's documented inline table-load endpoint. It
never provisions workspaces or databases, and never performs a network request
unless both ``--apply`` and ``--allow-replace`` are supplied. Hotdata may create
the target table as part of its first documented load.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import io
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.hotdata import (
    _DOCUMENT_COLUMNS,
    HotdataNativeClient,
    _load_table_path,
)
from app.config import Settings
from app.models import Document

INLINE_LIMIT_BYTES = 2 * 1024 * 1024


def corpus_to_csv(path: Path) -> tuple[str, int]:
    """Validate the local corpus and encode it as documented inline CSV."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise TypeError("corpus JSON must contain an array of documents")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(_DOCUMENT_COLUMNS)
    for item in raw:
        try:
            document = Document.model_validate(item)
        except (TypeError, ValueError) as error:
            raise ValueError("corpus contains an invalid document") from error
        writer.writerow(
            [
                document.id,
                document.title,
                document.content,
                document.product,
                document.version or "",
                document.published_at.isoformat(),
                document.document_type,
                json.dumps(document.tags, separators=(",", ":")),
            ]
        )
    csv_data = output.getvalue()
    if len(csv_data.encode("utf-8")) > INLINE_LIMIT_BYTES:
        raise ValueError(
            f"corpus CSV is larger than Hotdata's 2 MiB inline-load limit ({INLINE_LIMIT_BYTES} bytes)"
        )
    return csv_data, len(raw)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dry-run or explicitly load the RetrievalLab corpus into Hotdata")
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "app" / "data" / "corpus.json",
        help="local corpus JSON path",
    )
    parser.add_argument("--api-url", default=None)
    parser.add_argument("--workspace-id", default=None)
    parser.add_argument("--database-id", default=None)
    parser.add_argument("--table", default=None)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--apply", action="store_true", help="perform the replacement load")
    parser.add_argument(
        "--allow-replace",
        action="store_true",
        help="explicitly acknowledge that --apply replaces the target table",
    )
    return parser


def _print_dry_run(
    *, api_url: str, database_id: str, table: str, row_count: int, byte_count: int
) -> None:
    path = _load_table_path(database_id or "database-id", table)
    print("Hotdata corpus load dry-run")
    print(f"target: {api_url.rstrip('/')}{path}")
    print("mode: replace")
    print(f"rows: {row_count}")
    print(f"inline_bytes: {byte_count}/{INLINE_LIMIT_BYTES}")
    print("network: disabled (use --apply --allow-replace to execute)")


async def _apply_load(config: Settings, table: str, csv_data: str) -> int:
    client = HotdataNativeClient(
        config.hotdata_api_url,
        config.hotdata_api_key,
        config.hotdata_workspace_id,
        config.hotdata_database_id,
        config.request_timeout_seconds,
    )
    response = await client.load_csv(
        table,
        csv_data,
        # The corpus bytes are deterministic; use a stable key so a retry cannot
        # apply a different payload under the same idempotency key.
        hashlib.sha256(csv_data.encode("utf-8")).hexdigest()[:32],
        mode="replace",
    )
    print(f"status: {response.remote_mode if response.called else 'not-accepted'}")
    print(response.detail)
    return 0 if response.called else 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        overrides = {
            key: value
            for key, value in {
                "hotdata_api_url": args.api_url,
                "hotdata_workspace_id": args.workspace_id,
                "hotdata_database_id": args.database_id,
                "hotdata_table": args.table,
                "request_timeout_seconds": args.timeout,
            }.items()
            if value is not None
        }
        config = Settings(**overrides)
        table = config.hotdata_table
        database_id = config.hotdata_database_id or "database-id"
        csv_data, row_count = corpus_to_csv(args.corpus)
        # Validate the target before printing even a dry-run. This makes a
        # typo in the database/table visible without contacting Hotdata.
        _load_table_path(database_id, table)
    except OSError:
        print("error: unable to read the corpus", file=sys.stderr)
        return 2
    except json.JSONDecodeError:
        print("error: corpus is not valid JSON", file=sys.stderr)
        return 2
    except (TypeError, ValueError):
        print("error: invalid corpus or Hotdata configuration", file=sys.stderr)
        return 2
    _print_dry_run(
        api_url=config.hotdata_api_url,
        database_id=database_id,
        table=table,
        row_count=row_count,
        byte_count=len(csv_data.encode("utf-8")),
    )
    if not args.apply:
        return 0
    if not args.allow_replace:
        print("error: --apply requires --allow-replace because this is a replacement load", file=sys.stderr)
        return 2
    if not all(
        isinstance(value, str) and value.strip()
        for value in (config.hotdata_api_key, config.hotdata_workspace_id, config.hotdata_database_id)
    ):
        print("error: --apply requires Hotdata API key, workspace ID, and database ID in Settings/.env", file=sys.stderr)
        return 2
    return asyncio.run(_apply_load(config, table, csv_data))


if __name__ == "__main__":
    raise SystemExit(main())
