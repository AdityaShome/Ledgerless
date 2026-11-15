"""SQLite-backed local store per replica (guide 3.5).

Safety rules enforced here:
- a committed receipt is never overwritten or removed;
- an intent that is tombstoned can never be committed, and vice versa;
- every write bumps a monotonic version.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from recovery.intents import Intent
from recovery.receipts import Receipt

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v INTEGER);
CREATE TABLE IF NOT EXISTS intents(
  intent_id TEXT PRIMARY KEY, chain_id TEXT, digest TEXT, body TEXT, version INTEGER);
CREATE TABLE IF NOT EXISTS receipts(
  intent_id TEXT PRIMARY KEY, chain_id TEXT, digest TEXT, status TEXT, body TEXT, version INTEGER);
CREATE INDEX IF NOT EXISTS receipts_digest ON receipts(chain_id, digest, status);
"""


class StoreConflict(Exception):
    """Attempt to violate a safety rule (e.g. commit a tombstoned intent)."""


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(path))
        self.db.executescript(SCHEMA)
        self.db.execute("INSERT OR IGNORE INTO meta VALUES('version', 0)")
        self.db.commit()

    # -- versioning
    @property
    def version(self) -> int:
        return self.db.execute("SELECT v FROM meta WHERE k='version'").fetchone()[0]

    def _bump(self) -> int:
        self.db.execute("UPDATE meta SET v = v + 1 WHERE k='version'")
        return self.version

    # -- intents
    def record_intent(self, intent: Intent) -> None:
        """Durably declare an intent. Idempotent on intent_id."""
        if self.db.execute(
            "SELECT 1 FROM intents WHERE intent_id=?", (intent.intent_id,)
        ).fetchone():
            return
        v = self._bump()
        self.db.execute(
            "INSERT INTO intents VALUES(?,?,?,?,?)",
            (intent.intent_id, intent.chain_id, intent.digest, json.dumps(intent.to_dict()), v),
        )
        self.db.commit()

    def get_intent(self, intent_id: str) -> Intent | None:
        row = self.db.execute("SELECT body FROM intents WHERE intent_id=?", (intent_id,)).fetchone()
        return Intent.from_dict(json.loads(row[0])) if row else None

    # -- receipts
    def state(self, intent_id: str) -> str | None:
        """'committed' | 'tombstone' | 'declared' | None."""
        row = self.db.execute(
            "SELECT status FROM receipts WHERE intent_id=?", (intent_id,)
        ).fetchone()
        if row:
            return row[0]
        if self.db.execute("SELECT 1 FROM intents WHERE intent_id=?", (intent_id,)).fetchone():
            return "declared"
        return None

    def put_receipt(self, chain_id: str, receipt: Receipt) -> None:
        """Store a receipt. Idempotent for an identical receipt; conflicts raise."""
        existing = self.get_receipt(receipt.intent_id)
        if existing is not None:
            if existing == receipt:
                return
            raise StoreConflict(f"intent {receipt.intent_id} already {existing.status}")
        if receipt.status == "committed":
            dup = self.committed_for_digest(chain_id, receipt.digest)
            if dup is not None:
                raise StoreConflict(f"digest already committed by {dup.intent_id}")
        v = self._bump()
        self.db.execute(
            "INSERT INTO receipts VALUES(?,?,?,?,?,?)",
            (
                receipt.intent_id,
                chain_id,
                receipt.digest,
                receipt.status,
                json.dumps(receipt.to_dict()),
                v,
            ),
        )
        self.db.commit()

    def get_receipt(self, intent_id: str) -> Receipt | None:
        row = self.db.execute("SELECT body FROM receipts WHERE intent_id=?", (intent_id,)).fetchone()
        return Receipt.from_dict(json.loads(row[0])) if row else None

    def committed_for_digest(self, chain_id: str, digest: str) -> Receipt | None:
        """Dedup lookup by (chain_id, digest), not request id."""
        row = self.db.execute(
            "SELECT body FROM receipts WHERE chain_id=? AND digest=? AND status='committed'",
            (chain_id, digest),
        ).fetchone()
        return Receipt.from_dict(json.loads(row[0])) if row else None

    def receipts_for_chain(self, chain_id: str) -> list[tuple[str, Receipt]]:
        rows = self.db.execute(
            "SELECT chain_id, body FROM receipts WHERE chain_id=? ORDER BY version", (chain_id,)
        ).fetchall()
        return [(c, Receipt.from_dict(json.loads(b))) for c, b in rows]

    # -- tombstones are signed receipts with status 'tombstone'; the store only refuses
    # to write one if the intent already committed (put_receipt enforces that).

    # -- replica reconciliation
    def merge_from(self, other: Store) -> int:
        """Union of receipts from another replica's store. Returns number added."""
        added = 0
        for chain_id, body in other.db.execute("SELECT chain_id, body FROM receipts").fetchall():
            r = Receipt.from_dict(json.loads(body))
            if self.get_receipt(r.intent_id) is None:
                self.put_receipt(chain_id, r)
                added += 1
        for (body,) in other.db.execute("SELECT body FROM intents").fetchall():
            self.record_intent(Intent.from_dict(json.loads(body)))
        return added

    def close(self) -> None:
        self.db.close()
