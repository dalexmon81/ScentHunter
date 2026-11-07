from app.services.runtime_thread_snapshot import runtime_thread_snapshot


class FakeThread:
    name = "scenthunter-search-worker"
    ident = 101
    native_id = 202
    daemon = True

    def is_alive(self):
        return True


def test_runtime_thread_snapshot_includes_python_and_native_identity(tmp_path):
    task = tmp_path / "202"
    task.mkdir()
    (task / "comm").write_text("python-worker\\n")

    assert runtime_thread_snapshot(FakeThread(), str(tmp_path)) == {
        "name": "scenthunter-search-worker",
        "ident": 101,
        "native_id": 202,
        "alive": True,
        "daemon": True,
        "os_comm": "python-worker",
    }


def test_runtime_thread_snapshot_reports_unavailable_native_name(tmp_path):
    result = runtime_thread_snapshot(FakeThread(), str(tmp_path))

    assert result["native_id"] == 202
    assert result["os_comm_error"].startswith("FileNotFoundError:")


def test_runtime_thread_snapshot_skips_proc_lookup_without_native_id():
    class ThreadWithoutNativeId:
        name = "legacy-thread"
        ident = 7
        native_id = None
        daemon = False

        def is_alive(self):
            return False

    assert runtime_thread_snapshot(ThreadWithoutNativeId()) == {
        "name": "legacy-thread",
        "ident": 7,
        "native_id": None,
        "alive": False,
        "daemon": False,
    }
