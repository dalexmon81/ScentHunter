from app.services.runtime_memory_snapshot import runtime_memory_snapshot


def test_runtime_memory_snapshot_extracts_only_selected_counters(tmp_path):
    status = tmp_path / "status"
    status.write_text(
        "Name:\\tpython\\n"
        "VmPeak:\\t900 kB\\n"
        "VmRSS:\\t120 kB\\n"
        "VmSize:\\t450 kB\\n"
        "Threads:\\t7\\n"
    )

    assert runtime_memory_snapshot(status) == {
        "VmRSS": "120 kB",
        "VmSize": "450 kB",
        "Threads": "7",
    }


def test_runtime_memory_snapshot_returns_partial_values_for_malformed_lines(tmp_path):
    status = tmp_path / "status"
    status.write_text("VmRSS: 10 kB\\nVmSize: malformed\\nThreads: 2\\n")

    assert runtime_memory_snapshot(status) == {
        "VmRSS": "10 kB",
        "VmSize": "malformed",
        "Threads": "2",
    }


def test_runtime_memory_snapshot_fails_closed_for_missing_file(tmp_path):
    assert runtime_memory_snapshot(tmp_path / "missing") == {}
