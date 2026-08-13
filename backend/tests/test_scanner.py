"""Filesystem traversal."""

from sonicverse.scanner.scanner import AudioScanner


def test_collect_finds_audio_files_recursively(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "a.mp3").write_bytes(b"")
    (tmp_path / "nested" / "b.flac").write_bytes(b"")
    (tmp_path / "notes.txt").write_bytes(b"")

    found = AudioScanner(str(tmp_path)).collect()

    assert sorted(p.name for p in found) == ["a.mp3", "b.flac"]


def test_extension_matching_is_case_insensitive(tmp_path):
    (tmp_path / "loud.FLAC").write_bytes(b"")

    found = AudioScanner(str(tmp_path)).collect()

    assert [p.name for p in found] == ["loud.FLAC"]


def test_custom_extensions_narrow_the_search(tmp_path):
    (tmp_path / "a.mp3").write_bytes(b"")
    (tmp_path / "b.flac").write_bytes(b"")

    found = AudioScanner(str(tmp_path), extensions=[".flac"]).collect()

    assert [p.name for p in found] == ["b.flac"]


def test_missing_root_yields_nothing(tmp_path):
    assert AudioScanner(str(tmp_path / "does-not-exist")).collect() == []
