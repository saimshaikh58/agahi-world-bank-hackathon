"""Scripted conversations through the real engine (Test Console 'Scenario runner') and the template check."""
from __future__ import annotations

import itertools

from app import locations
from app.core import replies
from app.core.aliases import CROP_ORDER, HORIZON_LABEL, HORIZONS, crop_name
from app.core.engine import handle_message, reset_session
from app.core.sms import Part, sms_stats
from app.core.templates import finish, menu, t
from app.forecast.prep import MONTH_HORIZONS

SCEN_PREFIX = "+977980090"

# step = (input, check) ; check keys: state, intent, contains, not_contains, lang, segments_max
SCENARIOS: list[tuple[str, list[tuple[str, dict]]]] = [
    ("Onboarding: hello -> welcome", [("hello", {"state": "WELCOME", "contains": "1"})]),
    ("Onboarding: 1 -> location prompt", [("hi", {"state": "WELCOME"}), ("1", {"state": "ASK_LOCATION"})]),
    ("Onboarding: first message 1 skips welcome", [("1", {"state": "ASK_LOCATION"})]),
    ("Onboarding: invalid location x3 -> Not sure", [("1", {}), ("x", {"state": "ASK_LOCATION"}), ("y", {"state": "ASK_LOCATION"}),
                                                      ("z", {"state": "MAIN"})]),
    ("Onboarding: STOP during onboarding", [("hi", {}), ("stop", {"intent": "STOP"})]),
    ("Onboarding: LANG NE during onboarding", [("hi", {}), ("LANG NE", {"lang": "ne", "state": "WELCOME"}), ("1", {"state": "ASK_LOCATION"})]),
    ("Onboarding: 0 re-shows location prompt", [("1", {}), ("0", {"state": "ASK_LOCATION"})]),
    ("Onboarding: location by name", [("1", {}), ("dhading", {"state": "MAIN", "contains": "Dhading"})]),
    ("Onboarding: welcome repeats on other text", [("hi", {}), ("what", {"state": "WELCOME"}), ("ok", {"state": "WELCOME"})]),
    ("Location change via 6", [("1", {}), ("1", {}), ("6", {"state": "ASK_LOCATION"}), ("2", {"state": "MAIN"})]),
    ("Menu: price path", [("1", {}), ("4", {}), ("1", {"state": "PICK_CROP"}), ("1", {"state": "AFTER_PRICE", "intent": "PRICE"})]),
    ("Menu: forecast path", [("1", {}), ("4", {}), ("2", {}), ("1", {"state": "PICK_HORIZON"}), ("2", {"state": "AFTER_FORECAST"})]),
    ("Menu: forecast all horizons", [("1", {}), ("1", {}), ("2", {}), ("1", {"state": "PICK_HORIZON"})] +
     [x for n in range(1, 8) for x in ((str(n), {"state": "AFTER_FORECAST"}), ("1", {"state": "PICK_HORIZON"}))]),
    ("Menu: weather 7d / weeks / season", [("1", {}), ("1", {}), ("3", {"state": "WEATHER_MENU"}), ("1", {"state": "AFTER_WEATHER"}),
                                           ("1", {"state": "AFTER_WEATHER"}), ("2", {"state": "AFTER_WEATHER"})]),
    ("Menu: sell/hold", [("1", {}), ("1", {}), ("4", {}), ("2", {"state": "AFTER_ADVICE", "intent": "ADVICE"})]),
    ("Menu: arrivals", [("1", {}), ("1", {}), ("5", {}), ("1", {"state": "AFTER_ARRIVALS"})]),
    ("Price follow-up: 3 Arrivals, 4 Other crop", [("1", {}), ("1", {}), ("golbheda", {"state": "AFTER_PRICE"}),
                                                 ("3", {"state": "AFTER_ARRIVALS", "intent": "ARRIVALS"}),
                                                 ("1", {"state": "AFTER_PRICE"}), ("4", {"state": "PICK_CROP"})]),
    ("Quick option words", [("1", {}), ("1", {}), ("arrivals", {"state": "PICK_CROP"}), ("1", {"state": "AFTER_ARRIVALS"}),
                            ("weather", {"state": "WEATHER_MENU"}), ("sell", {"state": "PICK_CROP"}), ("price", {"state": "PICK_CROP"})]),
    ("Follow-up: and potato? / ani? / aru?", [("1", {}), ("1", {}), ("golbheda", {}), ("and potato?", {"intent": "PRICE"}),
                                              ("ani?", {"intent": "FORECAST"}), ("aru?", {"state": "PICK_CROP"})]),
    ("Menu: language switch", [("1", {}), ("1", {}), ("9", {"state": "LANG_MENU"}), ("1", {"lang": "en", "state": "MAIN"})]),
    ("Menu: crop paging with 8", [("1", {}), ("1", {}), ("1", {}), ("8", {"state": "PICK_CROP"}), ("1", {"state": "AFTER_PRICE"})]),
    ("0 from PICK_CROP", [("1", {}), ("1", {}), ("1", {}), ("0", {"state": "MAIN"})]),
    ("0 from PICK_HORIZON", [("1", {}), ("1", {}), ("2", {}), ("1", {}), ("0", {"state": "MAIN"})]),
    ("0 from AFTER_FORECAST", [("1", {}), ("1", {}), ("tomato 7 din", {"state": "AFTER_FORECAST"}), ("0", {"state": "MAIN"})]),
    ("0 from WEATHER_MENU", [("1", {}), ("1", {}), ("3", {}), ("0", {"state": "MAIN"})]),
    ("0 from LANG_MENU", [("1", {}), ("1", {}), ("9", {}), ("0", {"state": "MAIN"})]),
    ("0 from location re-pick", [("1", {}), ("1", {}), ("6", {}), ("0", {"state": "MAIN"})]),
    ("Free text: golbheda", [("1", {}), ("1", {}), ("golbheda", {"intent": "PRICE", "state": "AFTER_PRICE"})]),
    ("Free text: typo golvheda", [("1", {}), ("1", {}), ("golvheda", {"intent": "PRICE"})]),
    ("Free text: Devanagari गोलभेडा", [("1", {}), ("1", {}), ("गोलभेडा", {"intent": "PRICE", "lang": "ne"})]),
    ("Free text: tomato 14 din", [("1", {}), ("1", {}), ("tomato 14 din", {"intent": "FORECAST"})]),
    ("Free text: alu 2 hapta", [("1", {}), ("1", {}), ("alu 2 hapta", {"intent": "FORECAST"})]),
    ("Free text: follow-up 21 din? uses last crop", [("1", {}), ("1", {}), ("golbheda", {}), ("21 din?", {"intent": "FORECAST"})]),
    ("Free text: becham alu 500kg", [("1", {}), ("1", {}), ("becham alu 500kg", {"intent": "ADVICE", "contains": "500"})]),
    ("Free text: next month rain", [("1", {}), ("1", {}), ("next month rain", {"intent": "WEATHER"})]),
    ("Free text: weather in Dhading", [("1", {}), ("1", {}), ("weather in dhading", {"intent": "WEATHER", "contains": "Dhading"})]),
    ("Free text: gibberish -> menu", [("1", {}), ("1", {}), ("qwzx", {"state": "MAIN"})]),
    ("HELP always works", [("1", {}), ("1", {}), ("help", {"intent": "HELP"})]),
    ("STOP then START", [("1", {}), ("1", {}), ("stop", {"intent": "STOP"}), ("start", {"intent": "START"})]),
    ("Every reply <= 2 segments", [("1", {}), ("3", {}), ("LANG NE", {}), ("1", {"segments_max": 2}),
                                   ("1", {"segments_max": 2}), ("2", {"segments_max": 2})]),
]


def _check(r, exp: dict) -> str | None:
    if "state" in exp and r.state_after != exp["state"]:
        return f"state {r.state_after} != {exp['state']}"
    if "intent" in exp and r.intent != exp["intent"]:
        return f"intent {r.intent} != {exp['intent']}"
    if "lang" in exp and r.lang != exp["lang"]:
        return f"lang {r.lang} != {exp['lang']}"
    if "contains" in exp and exp["contains"] not in r.text:
        return f"text missing '{exp['contains']}'"
    if r.segments > exp.get("segments_max", 2):
        return f"{r.segments} segments"
    return None


def run(name: str | None = None) -> dict:
    """Run one or all scenarios with fresh numbers; numbers are deleted afterwards."""
    results = []
    for i, (sname, steps) in enumerate(SCENARIOS):
        if name and sname != name:
            continue
        phone = f"{SCEN_PREFIX}{i:04d}"
        reset_session(phone)
        transcript, err = [], None
        for text, exp in steps:
            r = handle_message("web", phone, text, offline=True)
            transcript.append({"in": text, "out": r.text, "state": r.state_after, "intent": r.intent})
            err = _check(r, exp)
            if err:
                break
        reset_session(phone)
        results.append({"name": sname, "passed": err is None, "detail": err or "ok", "transcript": transcript})
    return {"results": results, "passed": sum(r["passed"] for r in results), "total": len(results)}


def _cases(lang: str, crop: str, h: str, loc: str) -> dict[str, list[Part]]:
    """Worst-case versions of every data reply, built the same way as app.core.replies."""
    name, hl, ln = crop_name(crop, lang), HORIZON_LABEL[lang][h], replies.loc_name(loc, lang)
    big = dict(lo="12,345", hi="99,999", p0="44,444")
    status = "st_seasonal" if h in MONTH_HORIZONS else "st_indicative"
    head = Part(t(lang, "fc_head", crop=name, h=hl), 0, "head", True)
    cases = {
        "forecast": [head, Part(t(lang, "fc_range", lo=big["lo"], hi=big["hi"]), 0, "v", True),
                     Part(t(lang, "fc_up", pct="+999"), 1, "d"), Part(t(lang, "fc_now", p0=big["p0"]), 3, "n"),
                     Part(t(lang, status), 2, "s", True), Part(t(lang, "asof", d="30 Sep"), 3, "a"), menu(lang, "fc_opts")],
        "pattern": [head, Part(t(lang, "pattern", lo=big["lo"], hi=big["hi"]), 0, "v", True), menu(lang, "fc_opts")],
        "unavailable": [head, Part(t(lang, "unavailable"), 0, "v", True), menu(lang, "fc_opts")],
    }
    if h == "d7":
        cases["price"] = [Part(t(lang, "price_head", crop=name, variant=" (small, Indian)"), 0, "h", True),
                          Part(t(lang, "price", p="99,999", when=t(lang, "on", d="30 Sep")), 0, "v", True),
                          Part(t(lang, "ch_up", pct="+999"), 1, "c"), Part(t(lang, "asof", d="30 Sep"), 3, "a"),
                          Part(t(lang, "w_clim_some", loc=ln), 4, "w"), menu(lang, "price_opts")]
        cases["arrivals"] = [Part(t(lang, "arr_head", crop=name), 0, "h", True),
                             Part(t(lang, "arr_val", t="999", when=t(lang, "on", d="30 Sep")), 0, "v", True),
                             Part(t(lang, "arr_more", pct="+999"), 1, "c"), menu(lang, "arr_opts")]
        cases["advice"] = [Part(t(lang, "adv_head", crop=name, action=t(lang, "WAIT")), 0, "h", True),
                           Part(t(lang, "r_rain", loc=ln, mm=999), 1, "r", True), Part(t(lang, "r_nofc"), 2, "n", True),
                           Part(t(lang, "conf_low"), 2, "c", True), Part(t(lang, "qty", q="99,999", v="9,999,999"), 3, "q"),
                           menu(lang, "adv_opts")]
        cases["weather7"] = [Part(t(lang, "w7c_head", loc=ln), 0, "h", True),
                             Part(t(lang, "w7c_rain", word=t(lang, "rain_some"), tot=999), 0, "r", True),
                             Part(t(lang, "w7c_temp", lo=40, hi=45), 3, "t"), Part(t(lang, "past_years"), 2, "l", True),
                             menu(lang, "w_opts")]
        cases["confirmed"] = [Part(t(lang, "loc_saved", loc=ln), 0, "p", True),
                              menu(lang, "main_opts", replies.MAIN_NUMBERS, 1, True, with_menu=False)]
    return cases


def template_check() -> dict:
    """Render every reply template for all crops x horizons x locations x languages with worst-case numbers
    and line breaks; flag anything over 2 segments or needing truncation."""
    crops = list(CROP_ORDER)
    locs = [l["key"] for l in locations.all_locations()] or [locations.AREA_KEY]
    total, failures, max_seg = 0, [], 0
    for lang, crop, h, loc in itertools.product(("en", "rn", "ne"), crops, HORIZONS, locs):
        for kind, parts in _cases(lang, crop, h, loc).items():
            for sample in (False, True):
                text, dropped = finish(parts, lang, sample)
                st = sms_stats(text)
                total += 1
                max_seg = max(max_seg, st["segments"])
                if st["segments"] > 2 or "truncated" in dropped:
                    failures.append({"lang": lang, "crop": crop, "horizon": h, "location": loc, "kind": kind,
                                     "sample": sample, "segments": st["segments"], "text": text})
    for lang in ("en", "rn", "ne"):
        for r in (replies.welcome(lang), replies.location_prompt(lang, 0), replies.lang_menu(lang)):
            st = sms_stats(r.text)
            total += 1
            max_seg = max(max_seg, st["segments"])
            if st["segments"] > 2:
                failures.append({"lang": lang, "kind": "onboarding", "segments": st["segments"], "text": r.text})
    return {"total": total, "over": len(failures), "max_segments": max_seg, "failures": failures[:50]}
