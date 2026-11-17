"""recovery/resolveIntent JSON-RPC handler and client (guide 3.3)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from recovery.service import RecoveryService

METHOD = "recovery/resolveIntent"


def handle_resolve_request(service: RecoveryService, body: dict[str, Any]) -> dict[str, Any]:
    """Turn a JSON-RPC request body into a JSON-RPC response body."""
    rid = body.get("id")
    p = body.get("params") or {}
    try:
        result = service.resolve(p["chain_id"], p["intent_id"], p["digest"])
    except KeyError as e:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": f"missing {e}"}}
    return {"jsonrpc": "2.0", "id": rid, "result": result}


async def resolve_remote(
    url: str,
    chain_id: str,
    intent_id: str,
    digest: str,
    timeout: float = 5.0,
    http: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Call a peer's resolveIntent. Raises httpx errors if unreachable."""
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": METHOD,
        "params": {"chain_id": chain_id, "intent_id": intent_id, "digest": digest},
    }
    own = http is None
    client = http or httpx.AsyncClient(timeout=timeout)
    try:
        resp = await client.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    finally:
        if own:
            await client.aclose()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data["result"]
