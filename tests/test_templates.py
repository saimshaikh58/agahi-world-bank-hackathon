from app import scenarios
from app.core import replies, templates
from app.core.sms import sms_stats

BANNED = ("vs 7-day", "pattern only", "conformal", "P10", "P90", "climatology", "indicative", "Tmax", "estimate.")


def test_all_templates_within_two_segments_with_line_breaks():
    r = scenarios.template_check()
    assert r["total"] > 10000
    assert r["over"] == 0, r["failures"][:3]
    assert r["max_segments"] <= 2


def test_newlines_count_in_sms_stats():
    assert sms_stats("a\nb")["chars"] == 3
    assert sms_stats("a" * 159 + "\n")["segments"] == 1
    assert sms_stats("a" * 160 + "\n")["segments"] == 2


def test_replies_use_line_breaks_and_plain_words():
    for lang in ("en", "rn", "ne"):
        for r in (replies.price(lang, "tomato", "kathmandu_valley", True, False),
                  replies.arrivals(lang, "tomato", False), replies.weather7(lang, "kathmandu_valley", True, False),
                  replies.main_menu(lang)):
            assert "\n" in r.text
            assert not any(b.lower() in r.text.lower() for b in BANNED), r.text


def test_arrivals_words():
    t = templates
    assert t.change_word("en", 17, ("arr_more", "arr_less", "arr_same"), 10) == "More than usual (+17%)"
    assert t.change_word("en", -12, ("arr_more", "arr_less", "arr_same"), 10) == "Less than usual (-12%)"
    assert t.change_word("en", 9.9, ("arr_more", "arr_less", "arr_same"), 10) == "About normal"
    assert t.change_word("rn", 17, ("arr_more", "arr_less", "arr_same"), 10) == "Sadharan bhanda dherai (+17%)"


def test_price_menu_has_arrivals():
    r = replies.price("en", "tomato", "kathmandu_valley", True, False)
    assert "3 Arrivals" in r.text and "4 Other crop" in r.text and "0 Menu" in r.text
