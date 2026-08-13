"""Tag value coercion helpers - the messiest part of reading real-world files."""

import pytest

from sonicverse.metadata.parser import _first, _parse_year, _repair_id3_mojibake, _safe_int


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("3", 3),
        ("03", 3),
        ("3/12", 3),
        (" 7 ", 7),
        (5, 5),
        ("A1", None),
        ("", None),
        (None, None),
    ],
)
def test_safe_int(value, expected):
    assert _safe_int(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2003", 2003),
        ("2003-08-01", 2003),
        ("08/2003", 2003),
        ("no year here", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_year(value, expected):
    assert _parse_year(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (["a", "b"], "a"),
        (("a",), "a"),
        ("  padded  ", "padded"),
        (["   "], None),
        ([], None),
        (None, None),
    ],
)
def test_first(value, expected):
    assert _first(value) == expected


def test_id3_mojibake_repairs_gbk_as_latin1():
    # "听说你" encoded as GBK, then mis-decoded as Latin-1.
    mojibake = "听说你".encode("gbk").decode("latin-1")
    assert _fix_id3_mojibake(mojibake) == "听说你"


def test_id3_mojibake_leaves_valid_cjk_alone():
    assert _fix_id3_mojibake("听说你") == "听说你"


def test_id3_mojibake_leaves_ascii_alone():
    assert _fix_id3_mojibake("Hello") == "Hello"
