"""Training-corpus collection - append every QA-verified level to a dataset.

SAGA generates exactly the data it would need to fine-tune its own Coder -
a design brief in, a working game script out - and until now threw all of it
    away, since generated run workspaces are gitignored. This module keeps it.

Only levels that actually passed QA are recorded, so the corpus is
verified-good by construction rather than needing manual filtering later:
the script compiled, ran headlessly without errors, and satisfied its
template's contract check. That objective pass/fail signal is the unusual
part - most fine-tuning corpora have no ground truth beyond human taste.

One JSON object per line in datasets/coder_corpus.jsonl, which is directly
consumable as an instruction-tuning set (`prompt` -> `completion`).
Recording must never break a pipeline run, so every failure here is
swallowed with a warning.
"""

import json
import os
import time
from pathlib import Path

DATASET_DIR = Path(__file__).resolve().parent.parent.parent / "datasets"
CORPUS_PATH = DATASET_DIR / "coder_corpus.jsonl"


def _recording_enabled() -> bool:
    return os.environ.get("SAGA_RECORD_CORPUS", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }


def record_level(
    *,
    prompt: str | None,
    script: str,
    template: str,
    model: str | None,
    level_index: int,
    retry_count: int,
    design_doc: dict | None,
    vision_notes: list[str] | None,
) -> None:
    """Append one verified (brief -> script) pair. Never raises."""
    if not _recording_enabled() or not prompt or not script:
        return  # a fix/tune pass has no fresh brief; not a clean training pair
    try:
        doc = design_doc or {}
        level = (doc.get("levels") or [{}])[min(level_index, len(doc.get("levels") or [{}]) - 1)]
        record = {
            "schema_version": 2,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "template": template,
            "model": model,
            "level_index": level_index,
            "intensity": level.get("intensity"),
            "retry_count": retry_count,
            # retries > 0 means the first attempt was broken; the script here
            # is the repaired one, so the pair is still valid - but a trainer
            # may want to weight clean first-try generations higher.
            "first_try": retry_count == 0,
            "vision_notes": vision_notes or [],
            "verification": {
                "status": "passed",
                "gates": ["godot_startup", "runtime", "template_contract"],
            },
            "prompt": prompt,
            "completion": script,
        }
        DATASET_DIR.mkdir(parents=True, exist_ok=True)
        with CORPUS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        total = sum(1 for _ in CORPUS_PATH.open(encoding="utf-8"))
        print(f"[Corpus] Recorded verified {template} level -> {total} example(s) in {CORPUS_PATH.name}")
    except Exception as e:
        print(f"[Corpus] Recording skipped ({type(e).__name__}: {e})")
