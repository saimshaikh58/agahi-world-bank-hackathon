from app.core import nlu
from app.core.engine import handle_message


def say(phone, *texts):
    r = None
    for t in texts:
        r = handle_message("web", phone, t, offline=True)
    return r


def test_zero_returns_main_from_every_state(fresh_phone):
    say(fresh_phone, "1", "1")
    for path in (["1"], ["2"], ["2", "1"], ["3"], ["3", "1"], ["4"], ["5"], ["9"], ["1", "1"], ["6"]):
        say(fresh_phone, "0", *path)
        assert say(fresh_phone, "0").state_after == "MAIN", path


def test_paging_with_8(fresh_phone):
    say(fresh_phone, "1", "1", "1")
    r = say(fresh_phone, "8")
    assert r.state_after == "PICK_CROP"


def test_context_follow_up_uses_last_crop(fresh_phone):
    say(fresh_phone, "1", "1", "golbheda")
    r = say(fresh_phone, "21 din?")
    assert r.intent == "FORECAST" and r.crop == "tomato" and r.horizon == "d21"


def test_crop_aliases():
    for t in ("golbheda", "golvheda", "tamatar", "गोलभेडा", "tomato price"):
        assert nlu.parse(t).slots["crop"] == "tomato", t


def test_alu_two_weeks():
    r = nlu.parse("alu 2 hapta")
    assert r.intent == "FORECAST" and r.slots["crop"] == "potato" and r.slots["horizon"] == "d14"


def test_nepali_digits_parse():
    assert nlu.find_qty(nlu.normalise("५०० केजी")) == 500


def test_unknown_never_raises(fresh_phone):
    say(fresh_phone, "1", "1")
    r = say(fresh_phone, "qwzx plmk")
    assert r.state_after in ("MAIN", "CONFIRM")


def test_low_confidence_numbered_clarification(fresh_phone, monkeypatch):
    say(fresh_phone, "1", "1")
    monkeypatch.setattr(nlu.intent_model, "predict_proba", lambda s: {"PRICE": 0.5, "FORECAST": 0.4, "UNKNOWN": 0.1})
    monkeypatch.setattr(nlu, "find_crops", lambda s: ["tomato"])
    r = handle_message("web", fresh_phone, "something tomato like words here", offline=True)
    assert r.intent == "CLARIFY" and "1 " in r.text and "2 " in r.text


def test_heldout_intent_accuracy():
    import json

    from app.config import REPORTS_DIR
    ev = json.loads((REPORTS_DIR / "intent_eval.json").read_text())
    assert ev["accuracy"] >= 0.90
