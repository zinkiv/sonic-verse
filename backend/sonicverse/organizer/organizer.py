"""File organizer - moves confirmed tracks into the music library."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

from sonicverse.core.artists import join_artist_names
from sonicverse.core.config import get_settings
from sonicverse.core.paths import is_path_under, music_root, transfer_root
from sonicverse.metadata.parser import AudioMetadata

logger = logging.getLogger(__name__)

settings = get_settings()


class FileOrganizer:
    """Moves music files into the library as ``{artist}-{title}.{ext}``."""

    def __init__(
        self,
        root_path: str | None = None,
        template: str = "",
        filename_template: str = "{artist}-{title}.{ext}",
    ):
        self.root_path = Path(root_path or settings.music_path)
        self.template = template
        self.filename_template = filename_template

    def get_destination_path(
        self,
        metadata: AudioMetadata,
        file_path: str | Path,
    ) -> Path:
        """Calculate destination path based on template."""
        ext = Path(file_path).suffix.lstrip(".") or "mp3"

        artist = self._sanitize_path_component(
            join_artist_names(metadata.artist) or "Unknown Artist"
        )
        year = str(metadata.year) if metadata.year else "Unknown Year"
        album = self._sanitize_path_component(metadata.album or "Unknown Album")
        title = self._sanitize_path_component(metadata.title or "Unknown Track")
        track_num = metadata.track_number or 1

        filename = self.filename_template.format(
            artist=artist,
            title=title,
            track=track_num,
            ext=ext,
        )

        if not self.template:
            return self.root_path / filename

        dir_path = self.template.format(
            artist=artist,
            year=year,
            album=album,
        )
        return self.root_path / dir_path / filename

    def organize_file(
        self,
        source_path: str | Path,
        metadata: AudioMetadata,
        move: bool = True,
        destination: Path | None = None,
        overwrite: bool = True,
    ) -> Optional[Path]:
        """Organize a file to its destination.

        Returns the destination path, or None if the file was skipped.
        When ``overwrite`` is True (default), an existing destination file is
        replaced instead of creating ``name (2).ext``.
        """
        try:
            source = Path(source_path)
            destination = destination or self.get_destination_path(metadata, source)
            source_resolved = _safe_resolve(source)
            dest_resolved = _safe_resolve(destination)

            if source_resolved is not None and source_resolved == dest_resolved:
                logger.debug("Already in place: %s", source)
                return destination

            if destination.exists():
                if not overwrite:
                    logger.warning(
                        "Destination exists, skipping to avoid overwrite: %s",
                        destination,
                    )
                    return None
                if dest_resolved is None or dest_resolved != source_resolved:
                    destination.unlink(missing_ok=True)

            destination.parent.mkdir(parents=True, exist_ok=True)

            if move:
                shutil.move(str(source), str(destination))
            else:
                shutil.copy2(str(source), str(destination))

            prune_empty_parents(source.parent)
            return destination

        except Exception:
            logger.error("Failed to organize file: %s", source_path, exc_info=True)
            return None

    @staticmethod
    def _sanitize_path_component(name: str) -> str:
        """Sanitize a path component by removing invalid characters."""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, "_")

        name = name.strip(". ")

        if name.upper() in {
            "CON", "PRN", "AUX", "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }:
            name = f"_{name}"

        if len(name) > 100:
            name = name[:100]

        return name or "Unknown"


def path_keys(path: Path | str) -> set[str]:
    raw = Path(path)
    keys = {str(raw), raw.as_posix()}
    resolved = _safe_resolve(raw)
    if resolved is not None:
        keys.add(str(resolved))
        keys.add(resolved.as_posix())
    return keys


def _safe_resolve(path: Path) -> Path | None:
    try:
        return path.resolve()
    except OSError:
        return None


def prune_empty_parents(start: Path, stop_at: Path | None = None) -> None:
    """Remove empty directories up to (but not including) the library root."""
    try:
        current = start.resolve()
    except OSError:
        return

    if stop_at is None:
        if is_path_under(current, transfer_root()):
            stop_at = transfer_root()
        elif is_path_under(current, music_root()) or current == music_root().resolve():
            stop_at = music_root()
        else:
            return

    try:
        stop = stop_at.resolve()
    except OSError:
        return

    if current == stop or stop not in current.parents:
        return

    while current != stop:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
