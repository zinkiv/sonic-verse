"""Audio metadata parser."""

import base64
import logging
import os
import re
import struct
from dataclasses import dataclass
from pathlib import Path

from mutagen import File
from mutagen.id3 import ID3, Frames
from mutagen.mp3 import MP3
from mutagen.flac import FLAC, Picture
from mutagen.oggvorbis import OggVorbis
from mutagen.mp4 import MP4

logger = logging.getLogger(__name__)


@dataclass
class AudioMetadata:
    """Audio metadata container."""

    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    year: int | None = None
    genre: str | None = None
    track_number: int | None = None
    disc_number: int | None = None
    duration_ms: int | None = None
    cover_data: bytes | None = None
    bitrate: int | None = None
    sample_rate: int | None = None


def _safe_int(value: object) -> int | None:
    """Convert a value to int, tolerating '3/12', '03', 'A1' etc.

    Returns the leading numeric part, or None if there isn't one.
    """
    if value is None:
        return None
    match = re.match(r"\s*(\d+)", str(value))
    return int(match.group(1)) if match else None


def _parse_year(value: object) -> int | None:
    """Extract a 4-digit year from a date string like '2003-08-01' or '2003'."""
    if value is None:
        return None
    match = re.search(r"(\d{4})", str(value))
    return int(match.group(1)) if match else None


def _first(value: object) -> str | None:
    """Return the first element of a mutagen tag list as a string, or None."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        if not value:
            return None
        value = value[0]
    text = str(value).strip()
    return text or None


def _fix_id3_mojibake(text: str | None) -> str | None:
    """Repair Chinese ID3 text stored as Latin-1 but actually GBK/GB18030.

    Many ripped/downloaded MP3s mark ID3v2 text as encoding 0 (ISO-8859-1)
    while the bytes are GBK. Mutagen then yields mojibake like ``ÌýËµÄã``.
    If re-decoding as GB18030 yields CJK characters, prefer that.
    """
    if not text:
        return text
    if any("\u4e00" <= ch <= "\u9fff" for ch in text):
        return text
    try:
        repaired = text.encode("latin-1").decode("gb18030")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    if any("\u4e00" <= ch <= "\u9fff" for ch in repaired):
        return repaired.strip() or text
    return text


_NO_PICTURE_ID3_FRAMES = {key: cls for key, cls in Frames.items() if key not in {"APIC", "PIC"}}


class _ID3NoPictures(ID3):
    """ID3 loader that skips APIC/PIC so album art is not pulled off disk."""

    def load(self, filething, known_frames=None, translate=True, v2_version=4, load_v1=True):
        return super().load(
            filething,
            known_frames=_NO_PICTURE_ID3_FRAMES,
            translate=translate,
            v2_version=v2_version,
            load_v1=load_v1,
        )


def _parse_vorbis_comment_block(data: bytes) -> dict[str, list[str]]:
    tags: dict[str, list[str]] = {}
    if len(data) < 8:
        return tags
    vendor_len = struct.unpack_from("<I", data, 0)[0]
    pos = 4 + vendor_len
    if pos + 4 > len(data):
        return tags
    count = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    for _ in range(count):
        if pos + 4 > len(data):
            break
        length = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        raw = data[pos : pos + length].decode("utf-8", errors="replace")
        pos += length
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        tags.setdefault(key.upper(), []).append(value)
    return tags


def _flac_streaminfo_duration_ms(data: bytes) -> tuple[int | None, int | None]:
    """Return (duration_ms, sample_rate) from a FLAC STREAMINFO block."""
    if len(data) < 18:
        return None, None
    sample_rate = (data[10] << 12) | (data[11] << 4) | (data[12] >> 4)
    total_samples = (
        ((data[13] & 0x0F) << 32)
        | (data[14] << 24)
        | (data[15] << 16)
        | (data[16] << 8)
        | data[17]
    )
    if sample_rate <= 0:
        return None, None
    duration_ms = int(total_samples / sample_rate * 1000) if total_samples else None
    return duration_ms, sample_rate


def _read_flac_without_pictures(file_path: Path) -> AudioMetadata | None:
    """Read FLAC tags/duration while seeking past PICTURE blocks."""
    try:
        with open(file_path, "rb") as fh:
            if fh.read(4) != b"fLaC":
                return None
            metadata = AudioMetadata()
            comments: dict[str, list[str]] = {}
            while True:
                header = fh.read(4)
                if len(header) < 4:
                    break
                is_last = bool(header[0] & 0x80)
                block_type = header[0] & 0x7F
                length = int.from_bytes(header[1:4], "big")
                if block_type == 6:
                    fh.seek(length, os.SEEK_CUR)
                else:
                    data = fh.read(length)
                    if block_type == 0:
                        duration_ms, sample_rate = _flac_streaminfo_duration_ms(data)
                        metadata.duration_ms = duration_ms
                        metadata.sample_rate = sample_rate
                    elif block_type == 4:
                        comments = _parse_vorbis_comment_block(data)
                if is_last:
                    break
    except OSError:
        return None

    metadata.title = _first(comments.get("TITLE"))
    metadata.artist = _first(comments.get("ARTIST"))
    metadata.album = _first(comments.get("ALBUM"))
    metadata.album_artist = _first(comments.get("ALBUMARTIST"))
    metadata.year = _parse_year(_first(comments.get("DATE")))
    metadata.genre = _first(comments.get("GENRE"))
    metadata.track_number = _safe_int(_first(comments.get("TRACKNUMBER")))
    metadata.disc_number = _safe_int(_first(comments.get("DISCNUMBER")))
    return metadata


class MetadataReader:
    """Reads audio metadata from files."""

    @staticmethod
    def read(file_path: str | Path, include_cover: bool = True) -> AudioMetadata | None:
        """Read metadata from an audio file.

        Returns None only when the file cannot be parsed at all. Individual
        tag fields that fail to parse are skipped instead of aborting the
        whole read. ``include_cover=False`` skips embedded pictures (much
        faster on FLAC/MP3 libraries).
        """
        path = Path(file_path)
        if not include_cover and path.suffix.lower() == ".flac":
            light = _read_flac_without_pictures(path)
            if light is not None:
                return light

        try:
            if not include_cover and path.suffix.lower() == ".mp3":
                audio = MP3(path, ID3=_ID3NoPictures)
            else:
                audio = File(file_path)
        except Exception:
            logger.warning("Failed to parse audio file: %s", file_path, exc_info=True)
            return None

        if audio is None:
            logger.debug("Unsupported or unrecognized audio file: %s", file_path)
            return None

        try:
            if isinstance(audio, MP3):
                metadata = MetadataReader._read_mp3(audio)
            elif isinstance(audio, FLAC):
                metadata = MetadataReader._read_flac(audio)
            elif isinstance(audio, OggVorbis):
                metadata = MetadataReader._read_ogg(audio)
            elif isinstance(audio, MP4):
                metadata = MetadataReader._read_mp4(audio)
            else:
                metadata = AudioMetadata()
        except Exception:
            logger.warning("Failed to read tags from: %s", file_path, exc_info=True)
            metadata = AudioMetadata()

        # Duration/bitrate fallback for every format (incl. WAV/APE).
        if metadata.duration_ms is None:
            try:
                if audio.info is not None:
                    metadata.duration_ms = int(audio.info.length * 1000)
            except Exception:
                logger.debug("No stream info for: %s", file_path, exc_info=True)

        if not include_cover:
            metadata.cover_data = None
        return metadata

    @staticmethod
    def read_cover(file_path: str | Path) -> bytes | None:
        """Load only embedded album art (used when an album still has no cover)."""
        metadata = MetadataReader.read(file_path, include_cover=True)
        return metadata.cover_data if metadata else None

    @staticmethod
    def _read_mp3(audio: MP3) -> AudioMetadata:
        """Read MP3 (ID3v2) metadata."""
        metadata = AudioMetadata()
        if audio.tags:
            metadata.title = _fix_id3_mojibake(_first(audio.tags.get("TIT2")))
            metadata.artist = _fix_id3_mojibake(_first(audio.tags.get("TPE1")))
            metadata.album = _fix_id3_mojibake(_first(audio.tags.get("TALB")))
            metadata.album_artist = _fix_id3_mojibake(_first(audio.tags.get("TPE2")))
            metadata.year = _parse_year(
                _first(audio.tags.get("TDRC")) or _first(audio.tags.get("TYER"))
            )
            metadata.genre = _fix_id3_mojibake(_first(audio.tags.get("TCON")))
            metadata.track_number = _safe_int(_first(audio.tags.get("TRCK")))
            metadata.disc_number = _safe_int(_first(audio.tags.get("TPOS")))

            if hasattr(audio.tags, "getall"):
                apic_frames = audio.tags.getall("APIC")
                if apic_frames:
                    metadata.cover_data = apic_frames[0].data

        if audio.info:
            metadata.duration_ms = int(audio.info.length * 1000)
            metadata.bitrate = getattr(audio.info, "bitrate", None)
            metadata.sample_rate = getattr(audio.info, "sample_rate", None)

        return metadata

    @staticmethod
    def _read_flac(audio: FLAC) -> AudioMetadata:
        """Read FLAC (Vorbis Comment) metadata."""
        metadata = AudioMetadata()
        if audio.tags:
            metadata.title = _first(audio.tags.get("TITLE"))
            metadata.artist = _first(audio.tags.get("ARTIST"))
            metadata.album = _first(audio.tags.get("ALBUM"))
            metadata.album_artist = _first(audio.tags.get("ALBUMARTIST"))
            metadata.year = _parse_year(_first(audio.tags.get("DATE")))
            metadata.genre = _first(audio.tags.get("GENRE"))
            metadata.track_number = _safe_int(_first(audio.tags.get("TRACKNUMBER")))
            metadata.disc_number = _safe_int(_first(audio.tags.get("DISCNUMBER")))

        if audio.pictures:
            metadata.cover_data = audio.pictures[0].data

        if audio.info:
            metadata.duration_ms = int(audio.info.length * 1000)
            metadata.sample_rate = getattr(audio.info, "sample_rate", None)

        return metadata

    @staticmethod
    def _read_ogg(audio: OggVorbis) -> AudioMetadata:
        """Read Ogg Vorbis metadata."""
        metadata = AudioMetadata()
        if audio.tags:
            metadata.title = _first(audio.tags.get("TITLE"))
            metadata.artist = _first(audio.tags.get("ARTIST"))
            metadata.album = _first(audio.tags.get("ALBUM"))
            metadata.album_artist = _first(audio.tags.get("ALBUMARTIST"))
            metadata.year = _parse_year(_first(audio.tags.get("DATE")))
            metadata.genre = _first(audio.tags.get("GENRE"))
            metadata.track_number = _safe_int(_first(audio.tags.get("TRACKNUMBER")))
            metadata.disc_number = _safe_int(_first(audio.tags.get("DISCNUMBER")))

            # Embedded cover stored as base64-encoded FLAC picture block.
            blocks = audio.tags.get("METADATA_BLOCK_PICTURE", [])
            if blocks:
                try:
                    picture = Picture(base64.b64decode(blocks[0]))
                    metadata.cover_data = picture.data
                except Exception:
                    logger.debug("Failed to decode OGG cover art", exc_info=True)

        if audio.info:
            metadata.duration_ms = int(audio.info.length * 1000)

        return metadata

    @staticmethod
    def _read_mp4(audio: MP4) -> AudioMetadata:
        """Read MP4/M4A metadata."""
        metadata = AudioMetadata()
        if audio.tags:
            metadata.title = _first(audio.tags.get("\xa9nam"))
            metadata.artist = _first(audio.tags.get("\xa9ART"))
            metadata.album = _first(audio.tags.get("\xa9alb"))
            metadata.album_artist = _first(audio.tags.get("aART"))
            metadata.year = _parse_year(_first(audio.tags.get("\xa9day")))
            metadata.genre = _first(audio.tags.get("\xa9gen"))

            track = audio.tags.get("trkn")
            if track:
                metadata.track_number = _safe_int(track[0][0])
            disc = audio.tags.get("disk")
            if disc:
                metadata.disc_number = _safe_int(disc[0][0])

            covr = audio.tags.get("covr")
            if covr:
                metadata.cover_data = bytes(covr[0])

        if audio.info:
            metadata.duration_ms = int(audio.info.length * 1000)

        return metadata
