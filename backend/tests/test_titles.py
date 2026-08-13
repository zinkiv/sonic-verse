from sonicverse.core.titles import core_title


def test_core_title_strips_trailing_parens():
    assert core_title("青花瓷 (Tanii1.2x变速版)") == "青花瓷"
    assert core_title("青花瓷（粤语版）") == "青花瓷"
    assert core_title("听说你 (Live)") == "听说你"


def test_core_title_keeps_plain_name():
    assert core_title("青花瓷") == "青花瓷"
    assert core_title("  ") == ""
