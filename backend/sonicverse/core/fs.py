"""Filesystem permission helpers for tag writes and staging."""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger(__name__)


def ensure_file_writable(path: Path | str) -> None:
    """Best-effort: make ``path`` writable by the current process.

    Files dropped onto a NAS share are often owned by another UID or marked
    read-only. When we own the file, flip on owner write. When we do not own
    it, only a privileged startup ``chown`` (entrypoint) can fix ownership —
    this helper still documents the failure clearly via OSError later.
    """
    target = Path(path)
    if not target.is_file():
        return
    try:
        mode = target.stat().st_mode
    except OSError:
        return

    if os.access(target, os.W_OK):
        return

    # Owned by us (or we have CAP privileges): add owner write.
    try:
        target.chmod(mode | stat.S_IWUSR)
    except OSError as exc:
        logger.warning(
            "Cannot make file writable (uid=%s): %s (%s)",
            os.getuid(),
            target,
            exc,
        )
        return

    if not os.access(target, os.W_OK):
        logger.warning(
            "File still not writable after chmod (uid=%s): %s — "
            "check PUID/PGID matches the file owner, or restart the container "
            "so entrypoint can chown /data/transfer",
            os.getuid(),
            target,
        )
