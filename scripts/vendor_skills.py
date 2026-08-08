"""Vendor a pinned subset of the awesome-gamedev-agent-skills corpus.

SAGA does not install these the way a human developer would (`npx skills add`
wires them into an agent's own config, which does nothing for the GDScript SAGA
generates). Instead a curated subset is copied into the repo at an exact commit
and injected into specialist prompts by saga.skills, so a build is reproducible
and a skill can never change underneath a benchmark.

Upstream: https://github.com/gamedev-skills/awesome-gamedev-agent-skills
License: Apache-2.0 (LICENSE and NOTICE are vendored alongside the skills).

Usage:
    uv run python scripts/vendor_skills.py            # refresh at the pinned commit
    uv run python scripts/vendor_skills.py --check    # verify the tree matches
"""

import argparse
import base64
import json
import shutil
import sys
import urllib.request
from pathlib import Path

REPO = "gamedev-skills/awesome-gamedev-agent-skills"

# Pinned so a skill edit upstream can never silently change a build or
# invalidate a benchmark comparison. Bump deliberately, then re-run the
# OFF/ON benchmark before trusting the new text.
PINNED_SHA = "01b3eb41b359a6386e7d27c8a704baaa2a2fcfd9"
PINNED_DATE = "2026-07-25"

VENDOR_ROOT = Path(__file__).resolve().parent.parent / "vendor" / "gamedev-skills"

# Only the skills SAGA's system kinds actually route to. Every name here must
# be reachable from saga.skills.SKILL_ROUTES - an unrouted skill is dead weight
# in the repo and a live test failure.
SKILLS = [
    "godot/godot-2d-movement",
    "godot/godot-animation",
    "godot/godot-gdscript",
    "godot/godot-nodes-scenes",
    "godot/godot-physics",
    "godot/godot-resources",
    "godot/godot-signals-groups",
    "godot/godot-tilemap",
    "godot/godot-ui-control",
    "disciplines/camera-systems",
    "disciplines/dialogue-systems",
    "disciplines/game-ai",
    "disciplines/game-feel",
    "disciplines/game-ui-ux",
    "disciplines/level-design",
    "disciplines/save-systems",
    "genres/rpg",
]

LEGAL_FILES = ["LICENSE", "NOTICE"]


def _fetch(path: str) -> bytes:
    url = f"https://api.github.com/repos/{REPO}/contents/{path}?ref={PINNED_SHA}"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    return base64.b64decode(payload["content"])


def _targets() -> dict[str, Path]:
    targets = {f"skills/{skill}/SKILL.md": VENDOR_ROOT / skill / "SKILL.md" for skill in SKILLS}
    targets.update({name: VENDOR_ROOT / name for name in LEGAL_FILES})
    return targets


def vendor(check: bool) -> int:
    stale = []
    for remote, local in _targets().items():
        content = _fetch(remote)
        if check:
            current = local.read_bytes() if local.exists() else b""
            if current != content:
                stale.append(str(local.relative_to(VENDOR_ROOT.parent.parent)))
            continue
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(content)

    if check:
        for name in stale:
            print(f"stale: {name}")
        print(f"{len(stale)} file(s) differ from {REPO}@{PINNED_SHA[:12]}")
        return 1 if stale else 0

    (VENDOR_ROOT / "PIN.md").write_text(
        f"""# Vendored gamedev skills

Source: https://github.com/{REPO}
Commit: `{PINNED_SHA}` ({PINNED_DATE})
License: Apache-2.0 - see LICENSE and NOTICE in this directory.

These files are unmodified upstream copies. SAGA injects them into specialist
prompts through `saga.skills`; harness rules are always appended *after* this
text, because some skills assume a multi-script project while SAGA's template
Coder emits a single Level_N.gd.

Refresh or verify with:

    uv run python scripts/vendor_skills.py
    uv run python scripts/vendor_skills.py --check
""",
        encoding="utf-8",
    )
    print(f"Vendored {len(SKILLS)} skills from {REPO}@{PINNED_SHA[:12]} -> {VENDOR_ROOT}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the vendored tree matches the pinned commit instead of rewriting it",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove the vendored tree before fetching",
    )
    args = parser.parse_args()
    if args.clean and VENDOR_ROOT.exists():
        shutil.rmtree(VENDOR_ROOT)
    sys.exit(vendor(args.check))


if __name__ == "__main__":
    main()
