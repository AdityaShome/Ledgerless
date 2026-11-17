"""Per-agent recovery logic over a Store: begin / commit / resolve (guide 3.1-3.3)."""

from __future__ import annotations

from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from recovery.intents import Intent
from recovery.receipts import Receipt, make_receipt
from recovery.store import Store, StoreConflict


class RecoveryService:
    def __init__(self, store: Store, priv: Ed25519PrivateKey, org: str, recovering: bool = False):
        self.store = store
        self.priv = priv
        self.org = org
        self.recovering = recovering  # while True, resolveIntent answers "unknown"
        self._in_flight: set[str] = set()

    def begin(self, intent: Intent) -> tuple[str, Receipt | None]:
        """Declare an intent before any side effect.

        Returns ("proceed", None) to execute, ("done", receipt) if the digest already
        committed (dedup), or ("refused", receipt) if the intent was tombstoned.
        """
        existing = self.store.get_receipt(intent.intent_id)
        if existing is not None:
            return ("done" if existing.status == "committed" else "refused", existing)
        dup = self.store.committed_for_digest(intent.chain_id, intent.digest)
        if dup is not None:
            return "done", dup
        self.store.record_intent(intent)
        self._in_flight.add(intent.intent_id)
        return "proceed", None

    def commit(self, intent: Intent, effect_ref: str, prev: str | None) -> Receipt:
        """Write the signed committed receipt after the effect ran."""
        receipt = make_receipt(
            self.priv, intent.intent_id, intent.digest, "committed", effect_ref, prev
        )
        try:
            self.store.put_receipt(intent.chain_id, receipt)
        finally:
            self._in_flight.discard(intent.intent_id)
        return receipt

    def abandon(self, intent_id: str) -> None:
        """Effect did not run (error before it); leave the intent declared."""
        self._in_flight.discard(intent_id)

    def resolve(self, chain_id: str, intent_id: str, digest: str) -> dict[str, Any]:
        """recovery/resolveIntent: committed | tombstone | unknown."""
        if intent_id in self._in_flight or self.recovering:
            return {"state": "unknown"}
        r = self.store.get_receipt(intent_id)
        if r is not None:
            return {"state": r.status, "receipt": r.to_dict()}
        dup = self.store.committed_for_digest(chain_id, digest)
        if dup is not None:  # same effect committed under another request id
            return {"state": "committed", "receipt": dup.to_dict()}
        tomb = make_receipt(self.priv, intent_id, digest, "tombstone", None, None)
        try:
            self.store.put_receipt(chain_id, tomb)  # durable before answering
        except StoreConflict:
            return {"state": "unknown"}
        return {"state": "tombstone", "receipt": tomb.to_dict()}
