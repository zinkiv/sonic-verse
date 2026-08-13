"""Audio file scanner."""

import os
from pathlib import Path
from typing import Generator

from sonicverse.core.config import get_settings


settings = get_settings()


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
        if not self.root_path.exists():
            return

        for dirpath, _, filenames in os.walk(self.root_path):
            for filename in filenames:
                file_path = Path(dirpath) / filename
                if file_path.suffix.lower() in self.extensions:
                    try:
                        yield file_path.resolve()
                    except OSError:
                        yield file_path

    def collect(self) -> list[Path]:
        """Collect every audio file in a single traversal.

        Callers need both the total (for progress reporting) and the files
        themselves; walking twice doubles the I/O and the two passes can
        disagree if the directory changes in between.
        """
        return list(self.scan())
