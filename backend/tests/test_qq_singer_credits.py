"""QQ Music provider credit / avatar helpers."""

from sonicverse.providers.qqmusic import _singer_credits


def test_singer_credits_splits_combined_qq_name():
    artist_name, images = _singer_credits(
        [
            {
                "id": 1,
                "mid": "00022XKm1mqqQR",
                "name": "侯明昊;陈都灵;田嘉瑞;程潇",
            }
        ]
    )
    assert artist_name == "侯明昊,陈都灵,田嘉瑞,程潇"
    # Combined blob mid is not trusted for every person.
    assert all(not item.get("url") for item in images)
    assert [item["name"] for item in images] == [
        "侯明昊",
        "陈都灵",
        "田嘉瑞",
        "程潇",
    ]


def test_singer_credits_keeps_url_for_single_singer():
    artist_name, images = _singer_credits(
        [{"id": 1, "mid": "0018jrV33Zv6WP", "name": "许嵩"}]
    )
    assert artist_name == "许嵩"
    assert len(images) == 1
    assert images[0]["url"].endswith("T001R300x300M0000018jrV33Zv6WP.jpg")


def test_singer_credits_mixed_single_and_group():
    artist_name, images = _singer_credits(
        [
            {"mid": "aaa", "name": "张碧晨"},
            {"mid": "bbb", "name": "侯明昊;陈都灵"},
        ]
    )
    assert artist_name == "张碧晨,侯明昊,陈都灵"
    by_name = {item["name"]: item["url"] for item in images}
    assert by_name["张碧晨"].endswith("T001R300x300M000aaa.jpg")
    assert by_name["侯明昊"] == ""
    assert by_name["陈都灵"] == ""
