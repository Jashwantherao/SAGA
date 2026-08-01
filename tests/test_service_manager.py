from saga import service_manager


def test_restart_all_stops_then_starts_each_allowlisted_service(monkeypatch):
    definitions = {
        name: service_manager.ServiceDefinition(name, name, port, "http://test", ("test.exe",), "D:\\test")
        for name, port in (("ollama", 11434), ("comfyui", 8188), ("musicgen", 8189))
    }
    calls = []
    monkeypatch.setattr(service_manager, "_definitions", lambda: definitions)
    monkeypatch.setattr(service_manager, "stop_service", lambda name: calls.append(("stop", name)))
    monkeypatch.setattr(service_manager, "start_service", lambda name: calls.append(("start", name)) or {"name": name})
    monkeypatch.setattr(service_manager.time, "sleep", lambda _seconds: None)

    results = service_manager.control_services("restart", "all")

    assert [result["name"] for result in results] == ["ollama", "comfyui", "musicgen"]
    assert calls == [
        ("stop", "ollama"), ("start", "ollama"),
        ("stop", "comfyui"), ("start", "comfyui"),
        ("stop", "musicgen"), ("start", "musicgen"),
    ]


def test_start_reports_missing_launch_path(monkeypatch):
    definition = service_manager.ServiceDefinition(
        "comfyui", "ComfyUI", 8188, "http://127.0.0.1:8188/system_stats",
        ("D:\\missing\\python.exe", "main.py"), "D:\\missing", command_hint="Configure it.",
    )
    monkeypatch.setattr(service_manager, "_definitions", lambda: {"comfyui": definition})
    monkeypatch.setattr(service_manager, "_health", lambda _definition: {"running": False})

    result = service_manager.start_service("comfyui")

    assert result["status"] == "not_configured"
    assert "Configure it" in result["detail"]


def test_stop_action_only_stops_and_reports_status(monkeypatch):
    definitions = {
        "ollama": service_manager.ServiceDefinition(
            "ollama", "Ollama", 11434, "http://test", ("test.exe",), "D:\test"
        )
    }
    monkeypatch.setattr(service_manager, "_definitions", lambda: definitions)
    monkeypatch.setattr(
        service_manager, "stop_service", lambda name: {"name": name, "stopped_pids": [123]}
    )
    monkeypatch.setattr(
        service_manager, "start_service", lambda name: (_ for _ in ()).throw(AssertionError)
    )

    results = service_manager.control_services("stop", "ollama")

    assert results == [{"name": "ollama", "stopped_pids": [123], "status": "stopped"}]


def test_tail_service_log_returns_last_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(service_manager, "LOG_ROOT", tmp_path)
    (tmp_path / "ollama.log").write_text("one\ntwo\nthree\n", encoding="utf-8")

    result = service_manager.tail_service_log("ollama", lines=2)

    assert result["lines"] == ["two", "three"]
