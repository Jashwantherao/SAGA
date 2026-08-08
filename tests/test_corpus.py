from saga import corpus
import json


def test_recording_can_be_disabled_for_benchmarks(monkeypatch, tmp_path):
    target = tmp_path / "corpus.jsonl"
    monkeypatch.setattr(corpus, "CORPUS_PATH", target)
    monkeypatch.setenv("SAGA_RECORD_CORPUS", "0")

    corpus.record_level(
        prompt="brief", script="extends Node2D", template="collect", model="m",
        level_index=0, retry_count=0, design_doc={"levels": [{}]}, vision_notes=[],
    )

    assert not target.exists()


def test_recorded_rows_carry_explicit_qa_verification(monkeypatch, tmp_path):
    target = tmp_path / "corpus.jsonl"
    monkeypatch.setattr(corpus, "CORPUS_PATH", target)
    monkeypatch.setattr(corpus, "DATASET_DIR", tmp_path)
    monkeypatch.setenv("SAGA_RECORD_CORPUS", "1")

    corpus.record_level(
        prompt="brief", script="extends Node2D", template="collect", model="m",
        level_index=0, retry_count=0, design_doc={"levels": [{}]}, vision_notes=[],
    )

    record = json.loads(target.read_text(encoding="utf-8"))
    assert record["schema_version"] == 2
    assert record["verification"]["status"] == "passed"
    assert "template_contract" in record["verification"]["gates"]
