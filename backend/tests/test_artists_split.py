"""Tests for artist credit splitting and joining."""

from sonicverse.core.artists import (
    join_artist_names,
    normalize_artist_name,
    split_artist_names,
)


def test_split_keeps_single_name():
    assert split_artist_names("周杰伦") == ["周杰伦"]


def test_split_does_not_use_chinese_comma():
    assert split_artist_names("张三，李四") == ["张三，李四"]
    assert normalize_artist_name("爱，很简单") == "爱，很简单"
    assert join_artist_names("张三，李四") == "张三，李四"


def test_split_on_english_comma_and_ampersand():
    assert split_artist_names("Earth, Wind & Fire") == ["Earth", "Wind & Fire"]
    assert split_artist_names("周杰伦,费玉清") == ["周杰伦", "费玉清"]
    assert split_artist_names("MYTH & ROID") == ["MYTH & ROID"]
    assert split_artist_names("周杰伦 & 费玉清") == ["周杰伦 & 费玉清"]


def test_split_keeps_comma_inside_band_name():
    assert split_artist_names("Fear,and Loathing in Las Vegas") == [
        "Fear,and Loathing in Las Vegas"
    ]
    assert split_artist_names("Fear, and Loathing in Las Vegas") == [
        "Fear, and Loathing in Las Vegas"
    ]


def test_split_on_slash():
    assert split_artist_names("浅影阿 / 汐音社") == ["浅影阿", "汐音社"]
    assert split_artist_names("浅影阿/汐音社") == ["浅影阿", "汐音社"]


def test_split_on_semicolon():
    assert split_artist_names("侯明昊;陈都灵;田嘉瑞") == ["侯明昊", "陈都灵", "田嘉瑞"]
    assert split_artist_names("侯明昊；陈都灵；田嘉瑞") == ["侯明昊", "陈都灵", "田嘉瑞"]
    assert split_artist_names("A; B; C") == ["A", "B", "C"]


def test_split_dedupes_case_insensitively():
    assert split_artist_names("A, a, B") == ["A, a, B"]


def test_split_empty_and_none():
    assert split_artist_names(None) == []
    assert split_artist_names("   ") == []
    assert split_artist_names(" , & ") == []


def test_join_uses_english_comma_without_spaces():
    assert join_artist_names("周杰伦") == "周杰伦"
    assert join_artist_names("周杰伦, 费玉清") == "周杰伦,费玉清"
    assert join_artist_names(["周杰伦", "费玉清"]) == "周杰伦,费玉清"
    assert join_artist_names("周杰伦 & 费玉清") == "周杰伦 & 费玉清"
    assert join_artist_names("浅影阿 / 汐音社") == "浅影阿,汐音社"
    assert join_artist_names("侯明昊;陈都灵") == "侯明昊,陈都灵"
    assert join_artist_names(None) == ""


def test_normalize_strips_compat_and_invisible_chars():
    assert normalize_artist_name("  倉木麻衣  ") == "倉木麻衣"
    assert normalize_artist_name("倉木\u200b麻衣") == "倉木麻衣"
    assert normalize_artist_name("倉木　麻衣") == "倉木 麻衣"
    assert split_artist_names("倉木麻衣\u200b") == ["倉木麻衣"]
