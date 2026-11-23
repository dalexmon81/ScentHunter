import base64
import json
import os
from pathlib import Path
import shlex
import subprocess
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/fly-postgres-seed-readonly-diagnosis.yml"


@pytest.fixture
def runner(tmp_path):
    script = WORKFLOW.read_text().split("        run: |\n", 1)[1]
    script = textwrap.dedent(script)
    workflow_script = tmp_path / "workflow.sh"
    workflow_script.write_text(script)
    flyctl = tmp_path / "flyctl"
    flyctl.write_text(textwrap.dedent("""\
        #!/usr/bin/env python3
        import json, os, sys
        from pathlib import Path
        args = sys.argv[1:]
        if args[:2] == ["machines", "list"]:
            print(os.environ["MACHINES"])
        else:
            with open(os.environ["CALLS"], "a") as out:
                out.write(json.dumps(args) + "\\n")
            if args[args.index("-C") + 1] != "true":
                print("remote stderr", file=sys.stderr)
                print(os.environ.get("REMOTE_OUTPUT", "SCENTHUNTER_DIAGNOSIS_COMPLETED"))
                sys.exit(int(os.environ.get("REMOTE_STATUS", "0")))
        """))
    flyctl.chmod(0o755)
    calls = tmp_path / "calls"

    def run(machines, **overrides):
        env = os.environ | {
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(tmp_path),
            "FLY_API_TOKEN": "test-token",
            "FLY_APP": "scenthunter",
            "MACHINES": json.dumps(machines),
            "CALLS": str(calls),
        } | overrides
        result = subprocess.run(
            ["bash", str(workflow_script)], cwd=ROOT, env=env,
            capture_output=True, text=True, timeout=15,
        )
        invocations = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
        return result, invocations

    return run


def machine(id, state, group):
    return {"id": id, "state": state, "config": {"metadata": {"fly_process_group": group}}}


def test_selects_started_app_and_packages_both_checked_out_scripts(runner, tmp_path):
    result, calls = runner([
        machine("worker", "started", "worker"),
        machine("stopped", "stopped", "app"),
        machine("app", "started", "app"),
    ])
    assert result.returncode == 0, result.stderr
    assert "remote stderr" in result.stderr
    assert len(calls) == 2
    assert all(call[call.index("--machine") + 1] == "app" for call in calls)
    remote = shlex.split(calls[1][calls[1].index("-C") + 1])
    assert remote[:2] == ["sh", "-c"]
    parts = shlex.split(remote[2])
    assert parts[3:] == ["|", "base64", "-d", "|", "timeout", "-k", "10s", "480s", "sh"]
    payload = base64.b64decode(parts[2]).decode()
    assert subprocess.run(["sh", "-n"], input=payload, text=True).returncode == 0
    for name in ("diagnose_postgres_legacy_seed_gaps.py", "seed_postgres_fetch_queue_from_legacy_catalog.py"):
        expected = base64.b64encode((ROOT / "backend/scripts" / name).read_bytes()).decode()
        assert expected in payload
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(textwrap.dedent("""\
        #!/usr/bin/env python3
        import importlib.util
        from pathlib import Path
        import sys
        seed = Path(sys.argv[-1]).with_name("seed_postgres_fetch_queue_from_legacy_catalog.py")
        spec = importlib.util.spec_from_file_location("seed", seed)
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
        """))
    fake_python.chmod(0o755)
    seed = ROOT / "backend/scripts/seed_postgres_fetch_queue_from_legacy_catalog.py"
    payload = payload.replace(base64.b64encode(seed.read_bytes()).decode(), base64.b64encode(b"value = 1\n").decode())
    payload = payload.replace("test -r /data/store_catalog.sqlite3", ":")
    payload = payload.replace("test -x /app/.venv/bin/python", ":")
    payload = payload.replace("/app/.venv/bin/python -u", f"{shlex.quote(str(fake_python))} -u")
    payload = payload.replace("/tmp/scenthunter-diagnosis.XXXXXX", str(tmp_path / "remote.XXXXXX"))
    completed = subprocess.run(
        ["sh"], input=payload, text=True, capture_output=True,
        env=os.environ | {"SCENTHUNTER_MIGRATION_TARGET_DATABASE_URL": "test"},
    )
    assert completed.returncode == 0, completed.stderr
    assert "SCENTHUNTER_DIAGNOSIS_COMPLETED" in completed.stdout
    assert not list(tmp_path.glob("remote.*"))


def test_rejects_missing_started_app(runner):
    result, calls = runner([machine("worker", "started", "worker"), machine("app", "stopped", "app")])
    assert result.returncode != 0
    assert "No started app machine" in result.stderr
    assert not calls


@pytest.mark.parametrize("overrides", [
    {"REMOTE_STATUS": "124"},
    {"REMOTE_OUTPUT": "remote process exited without a success marker"},
])
def test_fails_when_remote_execution_times_out_or_has_no_success_marker(runner, overrides):
    result, _ = runner([machine("app", "started", "app")], **overrides)
    assert result.returncode != 0
    assert "::error::" in result.stdout
