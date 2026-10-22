"""Verify the real API boot hook keeps the next engine behind both opt-in flags.

These tests import the API in isolated subprocesses. They do not start a server,
contact production, write to the catalog, or access the database.
"""
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_api_import(next_enabled: str, preview_enabled: str) -> str:
    env = os.environ.copy()
    env["SCENTHUNTER_NEXT_ENABLED"] = next_enabled
    env["SCENTHUNTER_NEXT_PREVIEW_ENABLED"] = preview_enabled
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "backend"), str(ROOT), env.get("PYTHONPATH", "")]
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import main; "
                "routes = list(main.app.router.routes); "
                "paths = {getattr(route, 'path', '') for route in routes}; "
                "preview_routes = sorted("
                "str(getattr(route, 'path', '')) + ':' + "
                "','.join(sorted(getattr(route, 'methods', set()) or set())) "
                "for route in routes "
                "if getattr(route, 'path', None) == '/next-engine/preview'); "
                "print('MAIN_FILE=' + str(main.__file__)); "
                "print('NEXT_ENGINE_MOUNT_FLAG=' + str(getattr(main, '_NEXT_ENGINE_MOUNTED', None))); "
                "print('NEXT_ENGINE_PREVIEW_ROUTES=' + repr(preview_routes)); "
                "print('NEXT_ENGINE_ROUTE_PRESENT=' + "
                "str('/next-engine/preview' in paths))"
            ),
        ],
        cwd=ROOT / "backend",
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, (
        f"API import failed with flags {next_enabled}/{preview_enabled}: "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    return result.stdout + result.stderr


def test_real_api_boot_hook_keeps_preview_route_disabled_by_default():
    output = _run_api_import("0", "0")
    assert "NEXT_ENGINE_ROUTE_PRESENT=False" in output


def test_preview_flag_alone_does_not_mount_route():
    output = _run_api_import("0", "1")
    assert "NEXT_ENGINE_ROUTE_PRESENT=False" in output


def test_both_explicit_flags_mount_only_the_read_only_preview_route():
    output = _run_api_import("1", "1")
    assert "NEXT_ENGINE_PREVIEW_MOUNTED: POST /next-engine/preview" in output
    assert "NEXT_ENGINE_MOUNT_FLAG=True" in output, output
    assert "NEXT_ENGINE_ROUTE_PRESENT=True" in output, output
