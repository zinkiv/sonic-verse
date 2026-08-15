"""Release-year parsing for QQ / NetEase provider payloads."""

import pytest

from sonicverse.providers.year import parse_release_year


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (2003, 2003),
        ("2003", 2003),
        ("2003-07-31", 2003),
        ("20030731", 2003),
        (1059580800, 2003),
        (1059580800000, 2003),
        ("1059580800", 2003),
        (0, None),
        (True, None),
        (False, None),
        ("0", None),
        ("", None),
        (None, None),
        ("0000-00-00", None),
        ({"publishTime": 1059580800000}, 2003),
        ({"time_public": "1979-01-01"}, 1979),
        ({"publishTime": 0, "picUrl": "x"}, None),
        (-157766400000, 1965),
    ],
)
def test_parse_release_year(value, expected):
    assert parse_release_year(value) == expected


def test_parse_release_year_prefers_first_usable_value():
    assert parse_release_year(0, "", 1059580800) == 2003


def test_parse_release_year_does_not_take_digits_from_timestamp_string():
    # 1059 would be the naive first-four-digits extraction.
    assert parse_release_year("1059580800") == 2003
