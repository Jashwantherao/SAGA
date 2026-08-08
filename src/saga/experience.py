"""Bounded retrieval from SAGA's QA-verified generation history.

The corpus is not a bag of arbitrary model output: records are appended only
after Godot startup, runtime, and the template objective contract pass.  This
module turns that evidence into a small local memory for the Coder without
adding an embedding service or another model call.

Retrieval is deliberately conservative.  It never crosses mechanic-template
boundaries, prefers first-pass examples, deduplicates scripts, and includes a
record only when its complete script fits inside the prompt budget.  A chopped
GDScript example teaches syntax errors, so partial examples are never emitted.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from saga import corpus


TOKEN_RE = re.compile(r"[a-z][a-z0-9_]{2,}")
STOP_WORDS = {
    "and", "are", "for", "from", "game", "godot", "level", "must", "the",
    "this", "use", "with", "your",
}
LEGACY_REQUIRED_FIELDS = {
    "recorded_at", "template", "model", "level_index", "retry_count",
    "first_try", "prompt", "completion",
}

# A passed script can still be a poor teaching example. The first real A/B
# showed that repaired or very large references increased retries and latency
# even though the source game eventually passed QA. Keep memory high-signal
# until a larger benchmark justifies relaxing these limits.
DEFAULT_MIN_SIMILARITY = 0.20
DEFAULT_MAX_COMPLETION_CHARS = 8_000


@dataclass(frozen=True)
class VerifiedExperience:
    template: str
    model: str | None
    first_try: bool
    retry_count: int
    similarity: float
    completion: str
    verification_source: str


def _tokens(text: str) -> set[str]:
    return {
        token for token in TOKEN_RE.findall(text.lower())
        if token not in STOP_WORDS
    }


def _verification_source(record: dict) -> str | None:
    """Return the evidence source, or None when a row is not proven good."""
    verification = record.get("verification")
    if isinstance(verification, dict):
        return "qa_gates" if verification.get("status") == "passed" else None
    if "qa_verified" in record:
        return "qa_verified" if record.get("qa_verified") is True else None
    # Schema-v1 rows predate the explicit evidence field. They were written by
    # corpus.record_level at the same post-QA call site; require the complete
    # legacy signature rather than trusting any prompt/completion JSON object.
    if LEGACY_REQUIRED_FIELDS <= set(record):
        return "legacy_post_qa_corpus"
    return None


def retrieve_verified_experiences(
    *,
    template: str,
    query: str,
    limit: int = 1,
    corpus_path: str | Path | None = None,
    require_first_pass: bool = False,
    min_similarity: float = 0.0,
    max_completion_chars: int | None = None,
) -> list[VerifiedExperience]:
    """Return relevant complete scripts from the same mechanic template."""
    path = Path(corpus_path) if corpus_path is not None else corpus.CORPUS_PATH
    if limit <= 0 or not path.is_file():
        return []

    query_tokens = _tokens(query)
    candidates: list[tuple[tuple, int, VerifiedExperience]] = []
    seen_hashes: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    for index, line in enumerate(lines):
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(record, dict):
            continue
        source = _verification_source(record)
        completion = record.get("completion")
        if (
            source is None
            or record.get("template") != template
            or not isinstance(completion, str)
            or not completion.strip()
        ):
            continue
        completion = completion.strip()
        prompt_tokens = _tokens(str(record.get("prompt") or ""))
        similarity = (
            len(query_tokens & prompt_tokens) / len(query_tokens)
            if query_tokens else 0.0
        )
        try:
            retry_count = max(0, int(record.get("retry_count") or 0))
        except (TypeError, ValueError):
            continue
        digest = hashlib.sha256(completion.encode("utf-8")).hexdigest()
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        first_try = bool(record.get("first_try")) and retry_count == 0
        if require_first_pass and not first_try:
            continue
        if similarity < min_similarity:
            continue
        if max_completion_chars is not None and len(completion) > max_completion_chars:
            continue
        item = VerifiedExperience(
            template=template,
            model=record.get("model"),
            first_try=first_try,
            retry_count=retry_count,
            similarity=similarity,
            completion=completion,
            verification_source=source,
        )
        # Exact mechanic match is mandatory above. Within that safe set,
        # relevance wins, then clean first-pass quality, fewer repairs, and
        # finally the newer row for a deterministic tie break.
        rank = (similarity, first_try, -retry_count, index)
        candidates.append((rank, index, item))

    candidates.sort(key=lambda candidate: candidate[0], reverse=True)
    return [candidate[2] for candidate in candidates[:limit]]


def experience_context(
    *,
    template: str,
    query: str,
    limit: int = 1,
    max_chars: int = 12_000,
    corpus_path: str | Path | None = None,
) -> str:
    """Render complete verified examples within a strict character budget."""
    if max_chars <= 0:
        return ""
    blocks = []
    used = 0
    for item in retrieve_verified_experiences(
        template=template,
        query=query,
        limit=limit,
        corpus_path=corpus_path,
        require_first_pass=True,
        min_similarity=DEFAULT_MIN_SIMILARITY,
        max_completion_chars=min(max_chars, DEFAULT_MAX_COMPLETION_CHARS),
    ):
        quality = "first-pass" if item.first_try else f"repaired in {item.retry_count} retries"
        block = (
            "VERIFIED EXPERIENCE MEMORY (QA-passed reference only):\n"
            f"Mechanic: {item.template}; quality: {quality}; model: {item.model or 'unknown'}; "
            f"evidence: {item.verification_source}.\n"
            "Reuse structural gameplay patterns only. Do not copy its premise, "
            "asset filenames, labels, or balancing numbers. The current brief below "
            "is authoritative.\n"
            f"```gdscript\n{item.completion}\n```\n"
        )
        if used + len(block) > max_chars:
            continue
        blocks.append(block)
        used += len(block)
    return "\n".join(blocks)
