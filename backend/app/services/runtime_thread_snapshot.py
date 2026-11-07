"""Read-only Python/native Linux thread identity snapshot."""


def runtime_thread_snapshot(thread, proc_task_root="/proc/self/task"):
    """Return thread identity and, when readable, its native OS thread name."""
    native_id = getattr(thread, "native_id", None)
    item = {
        "name": thread.name,
        "ident": thread.ident,
        "native_id": native_id,
        "alive": thread.is_alive(),
        "daemon": thread.daemon,
    }
    if native_id is not None:
        try:
            with open(
                f"{proc_task_root}/{int(native_id)}/comm",
                "r",
                encoding="utf-8",
            ) as handle:
                item["os_comm"] = handle.read().strip()
        except (OSError, TypeError, ValueError) as exc:
            item["os_comm_error"] = f"{type(exc).__name__}: {exc}"
    return item
