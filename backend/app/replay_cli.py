"""Read-only, deterministic retrieval entry point executed by the local Rote Play.

Never calls the application HTTP endpoint, publishes memories, or invokes Rote
again. Credentials are loaded locally, never supplied in command arguments.
"""

import argparse
import asyncio
import json
import sys

from app.adapters.hotdata import HotdataQueryEngine
from app.config import Settings
from app.models import StrategyName
from app.services.query import understand_query
from app.services.retrieval import Corpus
from app.services.security import redact_sensitive


async def execute(query: str, strategy: str, top_k: int) -> dict:
    if not query.strip() or len(query) > 2000 or not 1 <= top_k <= 10:
        raise ValueError("query must contain 1-2000 characters and top_k must be 1-10")
    settings = Settings()
    corpus = Corpus(settings.corpus_path)
    profile = understand_query(redact_sensitive(query))
    result, integration = await HotdataQueryEngine(settings, corpus).execute(
        profile, StrategyName(strategy), top_k
    )
    return {
        "schema": "retrievallab.replay.v1",
        "query": profile.raw_query,
        "query_pattern": profile.signature,
        "corpus_version": corpus.version,
        "strategy_run": result.model_dump(mode="json"),
        "integration": integration.model_dump(mode="json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument(
        "--strategy", choices=[item.value for item in StrategyName], default="hybrid_rerank"
    )
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    try:
        print(json.dumps(asyncio.run(execute(args.query, args.strategy, args.top_k))))
        return 0
    except Exception as error:  # noqa: BLE001 - CLI boundary must not leak credential-bearing errors.
        print(
            f"Retrieval replay failed ({type(error).__name__}); check inputs and local configuration.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
