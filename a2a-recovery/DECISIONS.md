# Decisions

- D1: Python 3.12 (anaconda) used instead of 3.11; guide requires >=3.11 and 3.12 is the only compatible install. `requires-python = ">=3.11"`.
- D2: Pinned a2a-sdk==1.3.0 (latest at 2026-11-02). Revisit in Phase 3 if the API blocks middleware-only integration.
- D3: Package dirs (recovery, agents, bench, baselines) are top-level packages in one project, matching the guide layout.
