"""CLI entry point: turn a one-line game idea into a structured design doc.

Usage:
    uv run python -m saga.main "a puzzle platformer about a shape-shifting golem"
"""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from saga.graph import build_graph

OUTPUT_PATH = Path(__file__).resolve().parent.parent.parent / "output" / "design_doc.json"


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Generate a game design doc from a one-line idea.")
    parser.add_argument("idea", help="One-line game idea, e.g. 'a puzzle platformer about a shape-shifting golem'")
    args = parser.parse_args()

    graph = build_graph()
    result = graph.invoke({"user_prompt": args.idea, "design_doc": None})

    design_doc = result["design_doc"]
    print(json.dumps(design_doc, indent=2))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(design_doc, indent=2), encoding="utf-8")
    print(f"\nSaved to {OUTPUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
