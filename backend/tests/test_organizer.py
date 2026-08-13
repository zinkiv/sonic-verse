"""Destination path templating, rename format, and the no-overwrite guarantee."""

import pytest

from sonicverse.metadata.parser import AudioMetadata
from sonicverse.organizer.organizer import FileOrganizer


@pytest.fixture
def metadata():
    return AudioMetadata(
        title="晴天",
        artist="周杰伦",
        album="叶惠美",
        year=2003,
        track_number=1,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a<b>c", "a_b_c"),
        ("AC/DC", "AC_DC"),
        ('say "hi"', "say _hi_"),
        ("  .name.  ", "name"),
        ("CON", "_CON"),
        ("con", "_con"),
        ("LPT1", "_LPT1"),
        ("...", "Unknown"),
        ("", "Unknown"),
    ],
)
def test_sanitize_path_component(raw, expected):
    assert FileOrganizer._sanitize_path_component(raw) == expected


def test_sanitize_path_component_truncates():
    assert len(FileOrganizer._sanitize_path_component("a" * 150)) == 100


def test_destination_path_is_artist_dash_title(tmp_path, metadata):
    organizer = FileOrganizer(root_path=str(tmp_path))

    destination = organizer.get_destination_path(metadata, "/anywhere/original.flac")

    assert destination == tmp_path / "周杰伦-晴天.flac"


def test_destination_path_joins_multiple_artists_with_ampersand(tmp_path):
    organizer = FileOrganizer(root_path=str(tmp_path))
    metadata = AudioMetadata(title="千里之外", artist="周杰伦, 费玉清")

    destination = organizer.get_destination_path(metadata, "/anywhere/x.flac")

    assert destination == tmp_path / "周杰伦,费玉清-千里之外.flac"


def test_destination_path_falls_back_for_missing_tags(tmp_path):
    organizer = FileOrganizer(root_path=str(tmp_path))

    destination = organizer.get_destination_path(AudioMetadata(), "/anywhere/x.mp3")

    assert destination == tmp_path / "Unknown Artist-Unknown Track.mp3"


def test_organize_file_moves_by_default(tmp_path, metadata):
    organizer = FileOrganizer(root_path=str(tmp_path / "library"))
    source = tmp_path / "source.flac"
    source.write_bytes(b"audio")

    destination = organizer.organize_file(source, metadata)

    assert destination == organizer.get_destination_path(metadata, source)
    assert not source.exists()
    assert destination.read_bytes() == b"audio"


def test_organize_file_can_copy(tmp_path, metadata):
    organizer = FileOrganizer(root_path=str(tmp_path / "library"))
    source = tmp_path / "source.flac"
    source.write_bytes(b"audio")

    destination = organizer.organize_file(source, metadata, move=False)

    assert source.exists()
    assert destination.read_bytes() == b"audio"


def test_organize_file_overwrites_when_destination_exists(tmp_path, metadata):
    organizer = FileOrganizer(root_path=str(tmp_path / "library"))
    source = tmp_path / "source.flac"
    source.write_bytes(b"audio")

    destination = organizer.get_destination_path(metadata, source)
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"existing")

    result = organizer.organize_file(source, metadata)

    assert result == destination
    assert not source.exists()
    assert destination.read_bytes() == b"audio"


def test_organize_file_can_skip_overwrite(tmp_path, metadata):
    organizer = FileOrganizer(root_path=str(tmp_path / "library"))
    source = tmp_path / "source.flac"
    source.write_bytes(b"audio")

    destination = organizer.get_destination_path(metadata, source)
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"existing")

    assert organizer.organize_file(source, metadata, overwrite=False) is None
    assert source.exists()
    assert destination.read_bytes() == b"existing"


def test_organize_file_is_a_noop_when_already_in_place(tmp_path, metadata):
    organizer = FileOrganizer(root_path=str(tmp_path / "library"))
    destination = organizer.get_destination_path(metadata, "x.flac")
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"audio")

    assert organizer.organize_file(destination, metadata) == destination
    assert destination.read_bytes() == b"audio"
