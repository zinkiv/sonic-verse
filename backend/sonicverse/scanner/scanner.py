"""Audio file scanner."""

import os
from pathlib import Path
from typing import Generator

from sonicverse.core.config import get_settings


settings = get_settings()

# NAS / OS sidecars that can double a walk without holding real music.
_SKIP_DIR_NAMES = {
    "@eadir",
    "@recycle",
    "#recycle",
    ".@__thumb",
}


def _keep_dir(name: str) -> bool:
    lowered = name.lower()
    return not lowered.startswith(".") and lowered not in _SKIP_DIR_NAMES


class AudioScanner:
    """Scans directories for audio files."""

    def __init__(
        self,
        root_path: str | None = None,
        extensions: list[str] | None = None,
    ):
        self.root_path = Path(root_path or settings.music_path)
        self.extensions = set(extensions or settings.audio_extensions)

    def scan(self) -> Generator[Path, None, None]:
        """Scan directory for audio files."""
        try:
            root = self.root_path.resolve()
        except OSError:
            root = self.root_path
        if not root.exists():
            return

        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [name for name in dirnames if _keep_dir(name)]
            for filename in filenames:
                suffix = os.path.splitext(filename)[1].lower()
                if suffix not in self.extensions:
                    continue
                yield Path(dirpath) / filename

    def collect(self) -> list[Path]:
        """Collect every audio file in a single traversal.

        Callers need both the total (for progress reporting) and the files
        themselves; walking twice doubles the I/O and the two passes can
        disagree if the directory changes in between.
        """
        return list(self.scan())
