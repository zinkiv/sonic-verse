"""Audio tagger - writes metadata to audio files."""

import base64
import logging
from pathlib import Path

from mutagen import File
from mutagen.mp3 import MP3
from mutagen.flac import FLAC, Picture
from mutagen.oggvorbis import OggVorbis
from mutagen.mp4 import MP4, MP4Cover
from mutagen.id3 import APIC, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK

from sonicverse.core.fs import ensure_file_writable
from sonicverse.metadata.parser import AudioMetadata

logger = logging.getLogger(__name__)


def _detect_image_mime(data: bytes) -> str:
    """Detect image MIME type from magic bytes."""
    if data.startswith(b"\x89PNG"):
        return "image/png"
    return "image/jpeg"


class Tagger:
    """Writes metadata to audio files."""

    def write_metadata(self, file_path: str | Path, metadata: AudioMetadata) -> bool:
        """Write metadata to an audio file."""
        path = Path(file_path)
        try:
            ensure_file_writable(path)
            audio = File(path)
            if audio is None:
                logger.warning("Cannot write tags, unrecognized file: %s", path)
                return False

            if isinstance(audio, MP3):
                self._write_id3(audio, metadata)
            elif isinstance(audio, (FLAC, OggVorbis)):
                self._write_vorbis(audio, metadata)
            elif isinstance(audio, MP4):
                self._write_mp4(audio, metadata)
            else:
                logger.warning("Tag writing not supported for: %s", path)
                return False

            audio.save()
            return True

        except PermissionError:
            logger.error(
                "Permission denied writing tags to %s (process uid=%s). "
                "Set PUID/PGID to the owner of the transfer/music mounts, "
                "or restart the container so entrypoint can chown /data/transfer.",
                path,
                __import__("os").getuid(),
                exc_info=True,
            )
            return False
        except Exception:
            logger.error("Failed to write tags to: %s", path, exc_info=True)
            return False

    def _write_id3(self, audio: MP3, metadata: AudioMetadata) -> None:
        """Write ID3v2 tags to MP3."""
        if audio.tags is None:
            audio.add_tags()

        if metadata.title:
            audio.tags["TIT2"] = TIT2(encoding=3, text=[metadata.title])
        if metadata.artist:
            audio.tags["TPE1"] = TPE1(encoding=3, text=[metadata.artist])
        if metadata.album:
            audio.tags["TALB"] = TALB(encoding=3, text=[metadata.album])
        if metadata.album_artist:
            audio.tags["TPE2"] = TPE2(encoding=3, text=[metadata.album_artist])
        if metadata.year:
            audio.tags["TDRC"] = TDRC(encoding=3, text=[str(metadata.year)])
        if metadata.genre:
            audio.tags["TCON"] = TCON(encoding=3, text=[metadata.genre])
        if metadata.track_number:
            audio.tags["TRCK"] = TRCK(encoding=3, text=[str(metadata.track_number)])
        if metadata.disc_number:
            audio.tags["TPOS"] = TPOS(encoding=3, text=[str(metadata.disc_number)])

        if metadata.cover_data:
            audio.tags.delall("APIC")
            audio.tags["APIC:Cover"] = APIC(
                encoding=3,
                mime=_detect_image_mime(metadata.cover_data),
                type=3,  # Cover (front)
                desc="Cover",
                data=metadata.cover_data,
            )

    def _write_vorbis(self, audio: FLAC | OggVorbis, metadata: AudioMetadata) -> None:
        """Write Vorbis Comment tags to FLAC/Ogg."""
        if metadata.title:
            audio["TITLE"] = metadata.title
        if metadata.artist:
            audio["ARTIST"] = metadata.artist
        if metadata.album:
            audio["ALBUM"] = metadata.album
        if metadata.album_artist:
            audio["ALBUMARTIST"] = metadata.album_artist
        if metadata.year:
            audio["DATE"] = str(metadata.year)
        if metadata.genre:
            audio["GENRE"] = metadata.genre
        if metadata.track_number:
            audio["TRACKNUMBER"] = str(metadata.track_number)
        if metadata.disc_number:
            audio["DISCNUMBER"] = str(metadata.disc_number)

        if metadata.cover_data:
            picture = Picture()
            picture.data = metadata.cover_data
            picture.mime = _detect_image_mime(metadata.cover_data)
            picture.type = 3  # Cover (front)
            if isinstance(audio, FLAC):
                audio.clear_pictures()
                audio.add_picture(picture)
            else:
                # Ogg Vorbis stores covers as base64 FLAC picture blocks.
                audio["METADATA_BLOCK_PICTURE"] = [
                    base64.b64encode(picture.write()).decode("ascii")
                ]

    def _write_mp4(self, audio: MP4, metadata: AudioMetadata) -> None:
        """Write MP4/M4A tags."""
        if audio.tags is None:
            audio.add_tags()

        if metadata.title:
            audio["\xa9nam"] = [metadata.title]
        if metadata.artist:
            audio["\xa9ART"] = [metadata.artist]
        if metadata.album:
            audio["\xa9alb"] = [metadata.album]
        if metadata.album_artist:
            audio["aART"] = [metadata.album_artist]
        if metadata.year:
            audio["\xa9day"] = [str(metadata.year)]
        if metadata.genre:
            audio["\xa9gen"] = [metadata.genre]
        if metadata.track_number:
            audio["trkn"] = [(metadata.track_number, 0)]
        if metadata.disc_number:
            audio["disk"] = [(metadata.disc_number, 0)]

        if metadata.cover_data:
            imageformat = (
                MP4Cover.FORMAT_PNG
                if metadata.cover_data.startswith(b"\x89PNG")
                else MP4Cover.FORMAT_JPEG
            )
            audio["covr"] = [MP4Cover(metadata.cover_data, imageformat=imageformat)]
