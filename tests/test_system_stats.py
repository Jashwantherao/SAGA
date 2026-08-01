from saga import system_stats


def test_parse_gpu_line_reads_nvidia_smi_csv():
    parsed = system_stats.parse_gpu_line(
        "NVIDIA GeForce RTX 5070 Ti, 37, 1573, 16303, 48, 121.50"
    )

    assert parsed == {
        "name": "NVIDIA GeForce RTX 5070 Ti",
        "utilization": 37.0,
        "memory_used_mb": 1573.0,
        "memory_total_mb": 16303.0,
        "temperature": 48.0,
        "power_draw": 121.5,
    }


def test_parse_gpu_line_tolerates_malformed_output():
    assert system_stats.parse_gpu_line("garbage") is None
    parsed = system_stats.parse_gpu_line("GPU, [N/A], 1, 2, 3, [N/A]")
    assert parsed is not None and parsed["utilization"] is None


def test_system_stats_shape():
    stats = system_stats.system_stats()

    assert {"cpu_percent", "memory_used", "memory_total", "gpu"} <= set(stats)
