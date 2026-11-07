"""Read-only process memory snapshot from a Linux proc status file."""


def runtime_memory_snapshot(status_path):
    """Return selected memory/thread counters; tolerate unavailable proc data."""
    output = {}
    try:
        with open(status_path, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith(("VmRSS:", "VmSize:", "Threads:")):
                    key, value = line.split(":", 1)
                    output[key] = value.strip()
    except Exception:
        pass
    return output
