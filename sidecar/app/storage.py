import os
import shutil
import time
from pathlib import Path

_cache: dict[str, tuple[float, dict]] = {}
_TTL = 15.0  # seconds


def _walk_used_bytes(root: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(root, followlinks=False):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                continue
    return total


def compute_storage_snapshot(media_path: str) -> dict:
    """Used = size of files under MEDIA_PATH (not the host's total used).
    Capacity = filesystem size of the volume — so percent reflects the volume budget.
    """
    now = time.monotonic()
    cached = _cache.get(media_path)
    if cached and now - cached[0] < _TTL:
        return cached[1]

    root = Path(media_path)
    used = _walk_used_bytes(root) if root.exists() else 0
    try:
        total, _used_host, free_host = shutil.disk_usage(root)
    except OSError:
        total, free_host = 0, 0
    free = max(total - used, 0) if total else 0
    snap = {
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "percent_used": round(used * 100 / total, 2) if total else 0.0,
    }
    _cache[media_path] = (now, snap)
    return snap
