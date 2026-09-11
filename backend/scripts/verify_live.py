"""Bounded live checks; print statuses and counts, never credentials or user records."""

import asyncio
import json

import httpx

from app.adapters.cognee import CogneeMemoryConstructor
from app.adapters.hotdata import HotdataNativeClient, _qualified_identifier
from app.adapters.hydra import NativeHTTP as HydraHTTP
from app.config import Settings


async def main():
    settings = Settings()
    hotdata = HotdataNativeClient(
        settings.hotdata_api_url,
        settings.hotdata_api_key,
        settings.hotdata_workspace_id,
        settings.hotdata_database_id,
        15,
    )
    cognee = CogneeMemoryConstructor(settings).remote
    hydra = HydraHTTP(
        settings.hydradb_api_url,
        settings.hydradb_api_key,
        settings.hydradb_tenant_id,
        sub_tenant_id=settings.hydradb_sub_tenant_id,
        timeout=15,
    )

    async def probe(name, url, headers, payload):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(url, headers=headers, json=payload)
            result = {"provider": name, "http_status": response.status_code}
            try:
                data = response.json()
                result["json_type"] = type(data).__name__
                if isinstance(data, dict):
                    for field in ("rows", "chunks", "results"):
                        if isinstance(data.get(field), list):
                            result[f"{field}_count"] = len(data[field])
                    if name == "Hotdata" and response.is_success:
                        rows = data.get("rows")
                        if (
                            rows
                            and isinstance(rows[0], list)
                            and isinstance(rows[0][0], (int, float))
                        ):
                            result["corpus_rows"] = rows[0][0]
            except ValueError:
                result["json_type"] = "non-json"
            return result
        except httpx.HTTPError as error:
            return {"provider": name, "error_type": type(error).__name__}

    results = await asyncio.gather(
        probe(
            "Hotdata",
            hotdata.api_url + "/v1/query",
            hotdata._headers(),
            {
                "sql": f"SELECT COUNT(*) AS count FROM {_qualified_identifier(settings.hotdata_table)}"
            },
        ),
        probe(
            "Cognee",
            cognee.base_url + "/api/v1/search",
            cognee._headers(),
            {
                "query": "RetrievalLab verification",
                ("searchType" if cognee.auth_mode == "api_key" else "search_type"): "CHUNKS",
                "datasets": [settings.cognee_dataset],
                ("topK" if cognee.auth_mode == "api_key" else "top_k"): 1,
            },
        ),
        probe(
            "HydraDB",
            hydra.base_url + "/query",
            hydra._headers(),
            {
                **hydra._scope(),
                "query": "RetrievalLab verification",
                "type": "memory",
                "max_results": 1,
            },
        ),
    )
    print(json.dumps(results, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
