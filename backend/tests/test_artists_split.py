"""Tests for artist credit splitting and joining."""

from sonicverse.core.artists import join_artist_names, split_artist_names


def test_split_keeps_single_name():
    assert split_artist_names("周杰伦") == ["周杰伦"]


def test_split_on_english_comma_and_ampersand():
    assert split_artist_names("Earth, Wind & Fire") == ["Earth", "Wind", "Fire"]


def test_split_on_slash():
    assert split_artist_names("浅影阿 / 汐音社") == ["浅影阿", "汐音社"]
    assert split_artist_names("浅影阿/汐音社") == ["浅影阿", "汐音社"]


def test_split_dedupes_case_insensitively():
    assert split_artist_names("A, a & B") == ["A", "B"]


def test_split_empty_and_none():
    assert split_artist_names(None) == []
    assert split_artist_names("   ") == []
    assert split_artist_names(" , & ") == []


def test_join_uses_english_comma_without_spaces():
    assert join_artist_names("周杰伦") == "周杰伦"
    assert join_artist_names("周杰伦, 费玉清") == "周杰伦,费玉清"
    assert join_artist_names(["周杰伦", "费玉清"]) == "周杰伦,费玉清"
    assert join_artist_names("周杰伦 & 费玉清") == "周杰伦,费玉清"
    assert join_artist_names("浅影阿 / 汐音社") == "浅影阿,汐音社"
    assert join_artist_names(None) == ""
