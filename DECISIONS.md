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
