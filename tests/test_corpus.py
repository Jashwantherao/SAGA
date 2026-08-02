from saga import corpus


def test_recording_can_be_disabled_for_benchmarks(monkeypatch, tmp_path):
    target = tmp_path / "corpus.jsonl"
    monkeypatch.setattr(corpus, "CORPUS_PATH", target)
    monkeypatch.setenv("SAGA_RECORD_CORPUS", "0")

    corpus.record_level(
        prompt="brief", script="extends Node2D", template="collect", model="m",
        level_index=0, retry_count=0, design_doc={"levels": [{}]}, vision_notes=[],
    )

    assert not target.exists()
