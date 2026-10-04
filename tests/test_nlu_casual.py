import json

from app.config import ASSETS_DIR
from app.core import nlu
from app.core.engine import handle_message


def say(phone, *texts):
    r = None
    for t in texts:
        r = handle_message("web", phone, t, offline=True)
    return r


def test_multi_slot_sentence():
    r = nlu.parse("aaja kavre ma 500 kg golbheda 2 hapta pachi becham")
    s = r.slots
    assert s["crop"] == "tomato" and s["horizon"] == "d14" and s["location"] == "kavre_dhulikhel"
    assert s["qty"] == 500 and s["when"] == "today" and r.intent == "ADVICE"


def test_relative_words():
    assert nlu.parse("bholi paani parchha?").slots["when"] == "tomorrow"
    assert nlu.parse("parsi pani parla").slots["when"] == "day_after"
    assert nlu.parse("hijo ko bhau").slots["when"] == "yesterday"
    assert nlu.parse("tomato next week").slots["horizon"] == "d7"
    assert nlu.parse("pyaj aaglo mahina").slots["horizon"] == "m1"
    assert nlu.parse("yo hapta paani").slots["when"] == "this_week"


def test_spell_correction_and_guard():
    r = nlu.parse("cauliflwr prise")
    assert r.slots["crop"] == "cauliflower"
    r = nlu.parse("dhadng ma mausam")
    assert r.slots["location"] == "dhading_besi"
    fixed, fixes = nlu.spell_correct("pheri suru")
    assert fixes == []  # common words are never 'corrected' into crops
    assert nlu.parse("alert banda gara").intent == "STOP"


def test_shorthand_and_repeats():
    assert nlu.normalise("tmrw rain plzzzz") == "tomorrow rain plzz"
    assert nlu.parse("golbhedaaaa kti ho").slots["crop"] == "tomato"


def test_follow_ups(fresh_phone):
    say(fresh_phone, "1", "1", "LANG EN", "golbheda")
    r = say(fresh_phone, "and potato?")
    assert r.intent == "PRICE" and r.crop == "potato"
    r = say(fresh_phone, "ani?")
    assert r.intent == "FORECAST" and r.crop == "potato" and r.horizon == "d7"
    r = say(fresh_phone, "ani?")
    assert r.horizon == "d14"
    r = say(fresh_phone, "tyo ko 3 hapta?")
    assert r.intent == "FORECAST" and r.horizon == "d21"
    r = say(fresh_phone, "kati ho?")
    assert r.intent == "PRICE" and r.crop == "potato"
    r = say(fresh_phone, "aru?")
    assert r.state_after == "PICK_CROP"


def test_casual_set_size_and_accuracy():
    rows = [json.loads(l) for l in (ASSETS_DIR / "nlu_casual_test.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) >= 150
    ok = 0
    for r in rows:
        p = nlu.parse(r["text"])
        ok += p.intent == r["intent"] and (not r.get("crop") or p.slots["crop"] == r["crop"])
    assert ok / len(rows) >= 0.90


def test_training_data_volume():
    from collections import Counter
    rows = [json.loads(l) for l in (ASSETS_DIR / "nlu_training.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    c = Counter((r["intent"], r["lang"]) for r in rows)
    assert min(c.values()) >= 200


def test_heldout_accuracy_by_language():
    from app.config import REPORTS_DIR
    ev = json.loads((REPORTS_DIR / "intent_eval.json").read_text())
    assert ev["accuracy"] >= 0.92
    assert all(v >= 0.90 for v in ev["by_lang"].values())
    assert ev["chosen"] in ev["comparison"] and len(ev["comparison"]) == 2


def test_numpy_intent_model_matches_scikit_learn():
    import joblib
    import numpy as np

    from app.core import intent_model
    sk = joblib.load(intent_model.MODEL_PATH)
    lite = intent_model.get_model()
    texts = [nlu.normalise(t) for t in ("golbheda 14 din", "bholi paani parchha?", "alu becham ki rakhum", "zzzz", "गोलभेडा कति")]
    assert list(sk.classes_) == list(lite.classes_)
    assert np.abs(sk.predict_proba(texts) - lite.predict_proba(texts)).max() < 1e-4
