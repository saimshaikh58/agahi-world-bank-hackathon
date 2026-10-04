from app import db, locations
from app.core.engine import handle_message


def say(phone, *texts):
    r = None
    for t in texts:
        r = handle_message("web", phone, t, offline=True)
    return r


def test_new_number_any_text_gets_welcome(fresh_phone):
    r = say(fresh_phone, "hello")
    assert r.state_after == "WELCOME" and "1" in r.text


def test_one_shows_locations_from_file_not_boundary(fresh_phone):
    r = say(fresh_phone, "hi", "1")
    assert r.state_after == "ASK_LOCATION"
    for loc in locations.selectable():
        assert locations.short_name(loc, "rn") in r.text
    assert "boundary" not in r.text.lower()
    assert "Thaha chhaina" in r.text


def test_pick_saves_location_and_shows_main(fresh_phone):
    r = say(fresh_phone, "1", "4")
    assert r.state_after == "MAIN"
    assert db.q1("SELECT location FROM farmers WHERE phone=?", (fresh_phone,))["location"] == locations.selectable()[3]["key"]


def test_first_message_one_skips_welcome(fresh_phone):
    assert say(fresh_phone, "1").state_after == "ASK_LOCATION"


def test_three_invalid_saves_not_sure(fresh_phone):
    r = say(fresh_phone, "1", "x", "y", "z")
    assert r.state_after == "MAIN"
    assert db.q1("SELECT location FROM farmers WHERE phone=?", (fresh_phone,))["location"] == locations.AREA_KEY


def test_stop_and_lang_mid_onboarding(fresh_phone):
    r = say(fresh_phone, "hi", "LANG NE")
    assert r.lang == "ne" and r.state_after == "WELCOME"
    r = say(fresh_phone, "1", "stop")
    assert r.intent == "STOP"
    assert db.q1("SELECT subscribed FROM farmers WHERE phone=?", (fresh_phone,))["subscribed"] == 0


def test_six_reruns_picker_and_returning_user_skips(fresh_phone):
    say(fresh_phone, "1", "1")
    r = say(fresh_phone, "6")
    assert r.state_after == "ASK_LOCATION"
    r = say(fresh_phone, "2")
    assert r.state_after == "MAIN"
    assert say(fresh_phone, "hello").state_after != "WELCOME"


def test_weather_uses_saved_location(fresh_phone):
    say(fresh_phone, "1", "4")
    r = say(fresh_phone, "3", "1")
    assert locations.short_name(locations.selectable()[3], "rn") in r.text


def test_not_sure_uses_area_average(fresh_phone):
    say(fresh_phone, "1", "7")
    r = say(fresh_phone, "3", "1")
    assert "Sabai thau" in r.text
