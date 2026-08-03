# Vendored gamedev skills

Source: https://github.com/gamedev-skills/awesome-gamedev-agent-skills
Commit: `01b3eb41b359a6386e7d27c8a704baaa2a2fcfd9` (2026-07-25)
License: Apache-2.0 - see LICENSE and NOTICE in this directory.

These files are unmodified upstream copies. SAGA injects them into specialist
prompts through `saga.skills`; harness rules are always appended *after* this
text, because some skills assume a multi-script project while SAGA's template
Coder emits a single Level_N.gd.

Refresh or verify with:

    uv run python scripts/vendor_skills.py
    uv run python scripts/vendor_skills.py --check
