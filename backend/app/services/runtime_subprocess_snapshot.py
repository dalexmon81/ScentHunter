"""Read-only snapshot of Python worker subprocesses on Linux."""


def runtime_subprocess_snapshot(proc_root, current_pid):
    """Return visible Python processes, tolerating processes that exit mid-scan."""
    items = []
    if proc_root.exists():
        for entry in proc_root.iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            if pid == current_pid:
                continue
            try:
                cmdline = (
                    (entry / "cmdline")
                    .read_bytes()
                    .replace(b"\\x00", b" ")
                    .decode("utf-8", "replace")
                    .strip()
                )
                if not cmdline or "python" not in cmdline.lower():
                    continue
                stat = (entry / "stat").read_text(errors="replace").split()
                state = stat[2] if len(stat) > 2 else None
                items.append({"pid": pid, "state": state, "cmdline": cmdline[:500]})
            except (FileNotFoundError, PermissionError, OSError):
                continue
    return items
