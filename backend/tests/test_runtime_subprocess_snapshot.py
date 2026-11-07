from app.services.runtime_subprocess_snapshot import runtime_subprocess_snapshot


def _process(root, pid, cmdline, stat):
    entry = root / str(pid)
    entry.mkdir()
    (entry / "cmdline").write_bytes(cmdline)
    (entry / "stat").write_text(stat)


def test_snapshot_includes_python_process_and_skips_current_and_non_python(tmp_path):
    _process(tmp_path, 10, b"python worker.py\x00--queue\x00", "10 (python) S 1 2")
    _process(tmp_path, 11, b"/usr/bin/node server.js\x00", "11 (node) S 1 2")
    _process(tmp_path, 12, b"python current.py", "12 (python) R 1 2")

    assert runtime_subprocess_snapshot(tmp_path, 12) == [
        {"pid": 10, "state": "S", "cmdline": "python worker.py --queue"}
    ]


def test_snapshot_tolerates_missing_proc_files_and_truncates_command_line(tmp_path):
    (tmp_path / "13").mkdir()
    long_command = ("python " + "x" * 600).encode()
    _process(tmp_path, 14, long_command, "14 (python) R 1 2")

    result = runtime_subprocess_snapshot(tmp_path, 99)

    assert result == [{"pid": 14, "state": "R", "cmdline": long_command.decode()[:500]}]


def test_snapshot_returns_empty_for_missing_proc_root(tmp_path):
    assert runtime_subprocess_snapshot(tmp_path / "missing", 1) == []
