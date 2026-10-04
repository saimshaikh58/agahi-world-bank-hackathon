from app.core.sms import Part, fit_parts, sms_stats


def test_ascii_one_segment():
    s = sms_stats("Tomato Rs65/kg today")
    assert s["encoding"] == "GSM7" and s["segments"] == 1


def test_devanagari_over_70_is_ucs2_multi():
    s = sms_stats("गोलभेडा " * 12)
    assert s["encoding"] == "UCS2" and s["segments"] >= 2


def test_pipe_counts_double():
    assert sms_stats("|")["units"] == 2
    assert sms_stats("a" * 159 + "|")["segments"] == 2


def test_161_gsm_chars_two_segments():
    assert sms_stats("a" * 160)["segments"] == 1
    assert sms_stats("a" * 161)["segments"] == 2
    assert sms_stats("a" * 306)["segments"] == 2
    assert sms_stats("a" * 307)["segments"] == 3


def test_fit_drops_lowest_priority_first():
    parts = [Part("x" * 150, 0, "value", True), Part("y" * 100, 5, "menu"), Part("z" * 40, 1, "change")]
    text, dropped = fit_parts(parts, max_segments=1)
    assert "menu" in dropped and sms_stats(text)["segments"] == 1
