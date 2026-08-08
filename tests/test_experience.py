import json
from types import SimpleNamespace

from saga.experience import experience_context, retrieve_verified_experiences
from saga.agents import coder as coder_module


def _record(**overrides):
    return {
        "schema_version": 2,
        "recorded_at": "2026-08-08T10:00:00",
        "template": "collect",
        "model": "coder-a",
        "level_index": 0,
        "retry_count": 0,
        "first_try": True,
        "vision_notes": [],
        "verification": {"status": "passed", "gates": ["runtime"]},
        "prompt": "restore the orchard by collecting signal seeds",
        "completion": "extends Node2D\nfunc _ready():\n    pass",
    } | overrides


def _write(path, records):
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )


def test_retrieval_never_crosses_mechanic_templates(tmp_path):
    path = tmp_path / "corpus.jsonl"
    _write(path, [
        _record(template="collect", completion="extends Node2D\n# collect"),
        _record(template="dot_maze", completion="extends Node2D\n# maze"),
    ])

    found = retrieve_verified_experiences(
        template="collect", query="collect signal seeds", corpus_path=path
    )

    assert len(found) == 1
    assert "# collect" in found[0].completion


def test_retrieval_prefers_relevant_clean_first_pass_and_deduplicates(tmp_path):
    path = tmp_path / "corpus.jsonl"
    best = _record(completion="extends Node2D\n# orchard seed collector")
    _write(path, [
        _record(
            prompt="unrelated moon crystals",
            retry_count=2,
            first_try=False,
            completion="extends Node2D\n# repaired",
        ),
        best,
        best,
    ])

    found = retrieve_verified_experiences(
        template="collect", query="restore orchard signal seeds", limit=3,
        corpus_path=path,
    )

    assert "orchard seed collector" in found[0].completion
    assert found[0].first_try is True
    assert len(found) == 2


def test_failed_or_unproven_rows_are_not_memory(tmp_path):
    path = tmp_path / "corpus.jsonl"
    _write(path, [
        _record(verification={"status": "failed"}),
        {"template": "collect", "prompt": "x", "completion": "extends Node2D"},
    ])

    assert retrieve_verified_experiences(
        template="collect", query="x", corpus_path=path
    ) == []


def test_corrupt_rows_do_not_break_or_poison_later_valid_memory(tmp_path):
    path = tmp_path / "corpus.jsonl"
    completion = "extends Node2D\n# valid"
    records = [
        [],
        _record(retry_count="not-a-number", completion=completion),
        _record(completion=completion),
    ]
    _write(path, records)

    found = retrieve_verified_experiences(
        template="collect", query="orchard", corpus_path=path
    )

    assert len(found) == 1
    assert "# valid" in found[0].completion


def test_schema_v1_post_qa_rows_remain_usable(tmp_path):
    path = tmp_path / "corpus.jsonl"
    legacy = _record()
    legacy.pop("schema_version")
    legacy.pop("verification")
    _write(path, [legacy])

    found = retrieve_verified_experiences(
        template="collect", query="orchard", corpus_path=path
    )

    assert found[0].verification_source == "legacy_post_qa_corpus"


def test_context_never_emits_a_partial_script(tmp_path):
    path = tmp_path / "corpus.jsonl"
    _write(path, [_record(completion="extends Node2D\n" + "# long\n" * 100)])

    assert experience_context(
        template="collect", query="orchard", max_chars=100, corpus_path=path
    ) == ""


def test_context_labels_evidence_and_current_brief_as_authoritative(tmp_path):
    path = tmp_path / "corpus.jsonl"
    _write(path, [_record()])

    context = experience_context(
        template="collect", query="orchard", max_chars=2000, corpus_path=path
    )

    assert "QA-passed" in context
    assert "current brief below is authoritative" in context
    assert "```gdscript" in context


def test_context_rejects_repaired_low_similarity_and_oversized_examples(tmp_path):
    path = tmp_path / "corpus.jsonl"
    _write(path, [
        _record(
            prompt="restore orchard signal seeds",
            retry_count=1,
            first_try=False,
            completion="extends Node2D\n# repaired",
        ),
        _record(
            prompt="unrelated furnace reservoir",
            completion="extends Node2D\n# irrelevant",
        ),
        _record(
            prompt="restore orchard signal seeds",
            completion="extends Node2D\n" + "# large\n" * 1_200,
        ),
    ])

    assert experience_context(
        template="collect",
        query="restore orchard signal seeds",
        max_chars=20_000,
        corpus_path=path,
    ) == ""


def test_context_keeps_compact_similar_first_pass_example(tmp_path):
    path = tmp_path / "corpus.jsonl"
    _write(path, [_record(
        prompt="restore orchard signal seeds",
        completion="extends Node2D\n# compact first pass",
    )])

    context = experience_context(
        template="collect",
        query="restore orchard signal seeds",
        max_chars=20_000,
        corpus_path=path,
    )

    assert "compact first pass" in context


def test_coder_queries_memory_with_the_current_mechanic_and_level(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        coder_module,
        "settings",
        SimpleNamespace(
            experience_memory=True,
            experience_memory_limit=1,
            experience_memory_max_chars=5000,
        ),
    )
    monkeypatch.setattr(
        coder_module,
        "experience_context",
        lambda **kwargs: captured.update(kwargs) or "VERIFIED MEMORY",
    )
    design = {
        "title": "Signal Orchard",
        "mechanic_template": "collect",
        "story_premise": "Restore a storm-dark orchard.",
        "core_mechanics": ["collect signal seeds"],
        "win_condition": "Collect every seed.",
        "lose_condition": "none",
        "levels": [{
            "name": "The Grove", "description": "A broken signal grove.",
            "pressure_notes": "More drifting seeds.",
        }],
    }

    reference = coder_module._experience_reference(design, 0)

    assert captured["template"] == "collect"
    assert "Signal Orchard" in captured["query"]
    assert "The Grove" in captured["query"]
    assert reference == "VERIFIED MEMORY\n\n"
