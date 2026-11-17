# Decisions

- D1: Python 3.12 (anaconda) used instead of 3.11; guide requires >=3.11 and 3.12 is the only compatible install. `requires-python = ">=3.11"`.
- D2: Pinned a2a-sdk==1.3.0 (latest at 2026-11-02). Revisit in Phase 3 if the API blocks middleware-only integration.
- D3: Package dirs (recovery, agents, bench, baselines) are top-level packages in one project, matching the guide layout.
- D4: Repo root is D:\projects\Ledgerless (a2a-recovery/ subfolder flattened). Guide section 5 paths are relative to it.
- D5: Canonical JSON = sorted keys, compact separators, UTF-8 (no RFC 8785 dependency).
- D6: Receipt hash covers intent_id, digest, status, effect_ref, prev (not hash/sig); sig signs the hash string.
- D7: Digest granularity: coarse = action_type+target only; medium = per-tool listed keys; fine = all key params.
- D8: Tombstones are signed receipts with status "tombstone"; the store refuses commit-after-tombstone and tombstone-after-commit.
- D9: Store dedups on (chain_id, digest) among committed receipts; a tombstoned intent does not block a replay with a new intent_id (matches TLA+ model).
- D10: decide() adds two actions not in guide 3.4: WAIT (unreachable/unknown before timeout) and DISCARD (nothing ran or tombstoned, but upstream aborted). Invalid signature takes priority over every other rule. No intent and no receipt means no effect can have run, so REPLAY.
- D11: SDK 1.3.0 JSON-RPC dispatcher has a fixed method table (unknown method returns -32601), so recovery/resolveIntent cannot be registered inside it. Plan: wrap the SDK app in ASGI middleware that answers recovery/resolveIntent itself and forwards everything else untouched. Intents/receipts travel in Message.metadata under "x-recovery"; public keys in an AgentCard extension (AgentExtension uri+params). No SDK fork.
- D12: Added a2a-sdk[http-server] and uvicorn dependencies (Starlette is needed to serve).
- D13: Added recovery/service.py (begin/commit/abandon/resolve over a Store) alongside rpc.py; the guide's layout puts handler and client in rpc.py but the shared logic needs one home. Store opens SQLite with check_same_thread=False because the server runs in another thread; callers are serialised by the asyncio loop.
- D14: resolveIntent answers "unknown" while an intent is in flight or the service is flagged recovering; for an intent never seen, or declared but with no receipt, it durably writes a signed tombstone before answering. If the same digest is committed under a different intent id (re-plan), it answers committed with that receipt.
- D15: Delegation order matches the TLA+ model: a hop performs its own effect first, then delegates with parent_receipt = its receipt hash, so each receipt's prev is the parent hop's receipt. Responses return the receipt chain nested under x-recovery.downstream.
- D16: Assumption A1 carried into code: effect and receipt are one logical step. The toy tool does not yet model a crash between them; fault injection (Phase 4) will inject F1 as "crash after receipt written, before it is sent".
