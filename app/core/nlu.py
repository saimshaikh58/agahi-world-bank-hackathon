"""Understanding without an LLM: normalisation, SMS shorthand expansion, spell correction against the alias
vocabulary, multi-slot extraction, a small trained classifier, rule boosts and follow-up handling."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from app.core import aliases, intent_model

FUZZY_MIN = 85
ACT, ASK = 0.75, 0.45
SPELL_MIN = 82          # rapidfuzz ratio needed to correct a token
SPELL_MARGIN = 4        # skip correction when the two best different targets are this close (ambiguous)
SELL_WORDS = {"sell", "becham", "bechne", "bechu", "bechnu", "bechchu", "bechaun", "hold", "rakhne", "rakhu",
              "rakhum", "bechda", "rakhda", "keep", "बेच्ने", "बेचौं", "बेच्नु", "राख्ने", "बेचु", "राखौं", "बेच्दा"}
WEATHER_WORDS = {"rain", "weather", "mausam", "pani", "paani", "barsha", "barsat", "temperature", "garmi", "jado",
                 "ghaam", "sunny", "hot", "मौसम", "पानि", "वर्षा", "तापक्रम", "घाम"}
ARRIVAL_WORDS = {"arrival", "arrivals", "supply", "aagaman", "agaman", "aayo", "aawak", "came", "arrived",
                 "आगमन", "आयो", "आवक"}
FORECAST_WORDS = {"forecast", "badhcha", "ghatcha", "badhla", "ghatla", "hola", "next", "aaglo", "agami",
                  "future", "cheaper", "sasto", "mahango", "पूर्वानुमान", "बढ्छ", "घट्छ", "अर्को", "आगामी", "होला"}
# SMS shorthand -> full word (applied in normalise, so training and inference see the same text)
SHORTHAND = {"2day": "today", "tdy": "today", "tmrw": "tomorrow", "tmr": "tomorrow", "pls": "please", "plz": "please",
             "wat": "what", "wht": "what", "u": "you", "kti": "kati", "msm": "mausam", "wthr": "weather", "prc": "price",
             "hpta": "hapta", "bholy": "bholi", "aj": "aaja", "aja": "aaja", "aaj": "aaja", "wk": "week", "rt": "rate",
             "bhu": "bhau", "parxa": "parcha", "cha": "chha", "xa": "chha", "k": "ke", "grnus": "garnus"}
# Relative time words -> a 'when' slot
WHEN_WORDS = {"today": "today", "aaja": "today", "आज": "today", "tomorrow": "tomorrow", "bholi": "tomorrow",
              "भोलि": "tomorrow", "parsi": "day_after", "पर्सि": "day_after", "पर्सी": "day_after",
              "yesterday": "yesterday", "hijo": "yesterday", "हिजो": "yesterday"}
WHEN_PHRASES = {"next week": "next_week", "aaglo hapta": "next_week", "arko hapta": "next_week", "next hapta": "next_week",
                "अर्को हप्ता": "next_week", "आगामी हप्ता": "next_week", "this week": "this_week", "yo hapta": "this_week",
                "यो हप्ता": "this_week", "next month": "next_month", "aaglo mahina": "next_month",
                "arko mahina": "next_month", "अर्को महिना": "next_month"}
WHEN_HORIZON = {"next_week": "d7", "this_week": "d7", "next_month": "m1", "tomorrow": "d7", "day_after": "d7"}
# Follow-up markers ("ani?", "and potato?", "aru?")
FOLLOW_AND = {"ani", "and", "ra", "then", "aba", "what about", "अनि", "र"}
FOLLOW_OTHER = {"aru", "other", "arko", "another", "more", "अरु", "अरू", "अर्को"}
FILLER = {"hajur", "dai", "please", "ni", "la", "hai", "ke", "ta", "ok", "bhai", "sir", "?", "कृपया", "हजुर", "है"}
COMPARE_WORDS = {"vs", "compare", "tulana", "versus", "तुलना"}
QTY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|kilo|kilogram|keji|kg\.|quintal|q|ton|tonne|के ?जी|किलो|क्विन्टल)?")
UNIT_KG = {"quintal": 100, "q": 100, "क्विन्टल": 100, "ton": 1000, "tonne": 1000}
LANG_CMD = re.compile(r"^(?:lang|language|bhasha|भाषा)\s+(en|rn|ne|np)$")


@dataclass
class NluResult:
    """Parsed message."""
    intent: str
    confidence: float
    probs: dict = field(default_factory=dict)
    slots: dict = field(default_factory=dict)
    text: str = ""
    rule: str = ""


def normalise(text: str) -> str:
    """Lowercase, Nepali digits to ASCII, merge spelling variants, squeeze repeated letters, strip punctuation,
    expand SMS shorthand."""
    s = (text or "").lower().translate(aliases.TO_ASCII)
    s = s.replace("ू", "ु").replace("ी", "ि").replace("ण", "न").replace("ँ", "").replace("ं", "न्")
    s = re.sub(r"[^\w\sऀ-ॣ०-ॿ.]", " ", s)
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", s)
    s = re.sub(r"([a-z])\1{2,}", r"\1\1", s)  # "hooooo" -> "hoo"
    return " ".join(_split_suffix(SHORTHAND.get(t, t)) for t in s.split())


NE_SUFFIXES = ("भन्दा", "पछि", "देखि", "लाई", "बाट", "को", "का", "कि", "मा", "ले")


def _split_suffix(tok: str) -> str:
    """Devanagari case endings are written joined: 'आलुको' -> 'आलु को', 'दिनपछि' -> 'दिन पछि'."""
    if not re.search(r"[\u0900-\u097F]", tok):
        return tok
    for suf in NE_SUFFIXES:
        if tok.endswith(suf) and len(tok) - len(suf) >= 2:
            return tok[: -len(suf)] + " " + suf
    return tok


def _norm_alias(a: str) -> str:
    return normalise(a)


_CROP_INDEX: dict[str, str] = {}
_LOC_INDEX: dict[str, str] = {}


def _index() -> None:
    if not _CROP_INDEX:
        for crop, al in aliases.CROP_ALIASES.items():
            for a in al:
                _CROP_INDEX[_norm_alias(a)] = crop
        for key, al in aliases.LOCATION_ALIASES.items():
            for a in al:
                _LOC_INDEX[_norm_alias(a)] = key
    for a, crop in aliases.load_overrides().items():
        _CROP_INDEX[_norm_alias(a)] = crop


def _ngrams(tokens: list[str]) -> list[str]:
    return [" ".join(tokens[i:i + 2]) for i in range(len(tokens) - 1)] + tokens


STOP_CONTEXT = {"alert", "alerts", "sms", "garnus", "gara", "pathauna", "pathaunus", "suchana", "message", "messages",
                "सूचना", "गर", "गर्नुहोस्"}
AMBIGUOUS_CROP_WORDS = {"banda"}  # cabbage, but also "stopped/closed"


NON_CROP_INTENTS = {"WEATHER", "LOCATION", "LANG", "HELP", "MENU", "STOP", "START", "SMALLTALK", "UNKNOWN"}


def _non_crop_words() -> set[str]:
    """Frequent words from messages that never name a crop (menu, stop, weather...): never fuzzy-matched to a crop."""
    _spell_vocab()
    return _SPELL["non_crop"]


def find_crops(s: str) -> list[str]:
    """All crops mentioned (exact alias first, then fuzzy >= 85 on words that are not common words)."""
    _index()
    tokens = s.split()
    if set(tokens) & STOP_CONTEXT:
        tokens = [t for t in tokens if t not in AMBIGUOUS_CROP_WORDS]
    common = _non_crop_words()
    found: list[str] = []
    used: set[int] = set()
    for i in range(len(tokens)):
        for n in (2, 1):
            if i in used or i + n > len(tokens):
                continue
            g = " ".join(tokens[i:i + n])
            if g in _CROP_INDEX and _CROP_INDEX[g] not in found:
                found.append(_CROP_INDEX[g])
                used.update(range(i, i + n))
    for i, t in enumerate(tokens):
        if i in used or len(t) < 4 or t.isdigit() or t in common:
            continue
        best, score = None, 0.0
        for a, crop in _CROP_INDEX.items():
            if abs(len(a) - len(t)) > 3 or " " in a:
                continue
            sc = fuzz.ratio(t, a)
            if sc > score:
                best, score = crop, sc
        if best and score >= FUZZY_MIN and best not in found:
            found.append(best)
    return found


def find_location(s: str) -> str | None:
    """Location key mentioned in the text."""
    _index()
    for g in _ngrams(s.split()):
        if g in _LOC_INDEX:
            return _LOC_INDEX[g]
    return None


def find_horizon(s: str) -> str | None:
    """Map '14 din', '2 hapta', 'next month', '3 mahina' to a horizon key."""
    tokens = s.split()
    unit_of = {}
    for unit, words in aliases.HORIZON_UNITS.items():
        for w in words:
            unit_of[_norm_alias(w)] = unit
    for i, t in enumerate(tokens):
        if t in unit_of:
            unit = unit_of[t]
            n = 1
            if i > 0 and re.fullmatch(r"\d+", tokens[i - 1]):
                n = int(tokens[i - 1])
            elif i + 1 < len(tokens) and re.fullmatch(r"\d+", tokens[i + 1]):
                n = int(tokens[i + 1])
            return _to_horizon(unit, n)
        m = re.fullmatch(r"(\d+)(din|d|day|days|hapta|wk|week|weeks|mahina|month|months|m)", t)
        if m:
            u = m.group(2)
            unit = "day" if u in ("din", "d", "day", "days") else "week" if u in ("hapta", "wk", "week", "weeks") else "month"
            return _to_horizon(unit, int(m.group(1)))
    return None


def _to_horizon(unit: str, n: int) -> str:
    if unit == "month":
        return f"m{max(1, min(3, n))}"
    days = n * 7 if unit == "week" else n
    if days > 31:
        return f"m{max(1, min(3, round(days / 30)))}"
    return min(("d7", "d14", "d21", "d28"), key=lambda h: abs(int(h[1:]) - days))


def find_qty(s: str) -> float | None:
    """Quantity in kg if a number with a unit, or a bare number >= 20."""
    for m in QTY_RE.finditer(s):
        num, unit = float(m.group(1)), (m.group(2) or "").strip()
        if unit:
            return num * UNIT_KG.get(unit, 1)
        if num >= 20 and not find_horizon(s):
            return num
    return None


def find_variant(s: str) -> str | None:
    """indian / nepali / large / small."""
    toks = set(s.split())
    for key, words in aliases.VARIANT_WORDS.items():
        if toks & {_norm_alias(w) for w in words}:
            return key
    return None


def lang_command(s: str) -> str | None:
    """'lang ne' / 'LANG EN' -> language code."""
    m = LANG_CMD.match(s)
    if not m:
        return None
    return "ne" if m.group(1) in ("ne", "np") else m.group(1)


def detect_lang(text: str) -> str | None:
    """'ne' if Devanagari present, 'en' if clear English words, else None (keep current)."""
    if re.search(r"[ऀ-ॿ]", text or ""):
        return "ne"
    low = (text or "").lower()
    en_words = {"price", "weather", "today", "sell", "rain", "forecast", "how", "what", "the", "please", "help",
                "should", "will", "next", "days", "week", "month"}
    rn_words = {"ko", "bhau", "kati", "din", "hapta", "mahina", "aaja", "bholi", "pani", "mausam", "becham", "ma", "cha", "parcha"}
    toks = set(re.findall(r"[a-z]+", low))
    if len(toks & en_words) > len(toks & rn_words):
        return "en"
    if toks & rn_words:
        return "rn"
    return None


_SPELL: dict = {}


def _spell_vocab() -> tuple[dict[str, str], set[str]]:
    """Correction targets (alias word -> canonical id) and known words that are never corrected."""
    if _SPELL:
        return _SPELL["targets"], _SPELL["known"]
    _index()
    targets: dict[str, str] = {}
    for a, crop in _CROP_INDEX.items():
        if " " not in a and len(a) >= 4:
            targets[a] = f"crop:{crop}"
    for a, key in _LOC_INDEX.items():
        if " " not in a and len(a) >= 4:
            targets[a] = f"loc:{key}"
    for unit, words in aliases.HORIZON_UNITS.items():
        for w in words:
            if len(w) >= 4:
                targets[normalise(w)] = f"unit:{unit}"
    for name, words in (("sell", SELL_WORDS), ("weather", WEATHER_WORDS), ("arrival", ARRIVAL_WORDS),
                        ("forecast", FORECAST_WORDS)):
        for w in words:
            if len(w) >= 4:
                targets.setdefault(w, f"kw:{name}:{w}")
    known: set[str] = set(targets)
    counts: dict[str, int] = {}
    non_crop: dict[str, int] = {}
    for e in intent_model.load_examples():
        for tok in normalise(e["text"]).split():
            counts[tok] = counts.get(tok, 0) + 1
            if e["intent"] in NON_CROP_INTENTS:
                non_crop[tok] = non_crop.get(tok, 0) + 1
    known |= {w for w, n in counts.items() if n >= 3}
    _SPELL.update(targets=targets, known=known,
                  non_crop={w for w, n in non_crop.items() if n >= 3 and w not in _CROP_INDEX})
    return targets, known


def spell_correct(s: str) -> tuple[str, list[tuple[str, str]]]:
    """Replace unknown tokens with the closest alias word when the match is clear (rapidfuzz).
    Ambiguous tokens (two different targets nearly as close) are left alone."""
    targets, known = _spell_vocab()
    out, fixes = [], []
    for tok in s.split():
        if len(tok) < 4 or tok in known or tok.isdigit() or re.search(r"\d", tok):
            out.append(tok)
            continue
        scored = sorted(((fuzz.ratio(tok, w), w) for w in targets if abs(len(w) - len(tok)) <= 3), reverse=True)
        if not scored or scored[0][0] < SPELL_MIN:
            out.append(tok)
            continue
        best_score, best = scored[0]
        rival = next((sc for sc, w in scored[1:] if targets[w].split(":")[:2] != targets[best].split(":")[:2]), 0)
        if best_score - rival < SPELL_MARGIN:
            out.append(tok)
            continue
        out.append(best)
        fixes.append((tok, best))
    return " ".join(out), fixes


def find_when(s: str) -> str | None:
    """Relative time words: today, tomorrow, day_after, yesterday, this_week, next_week, next_month."""
    for phrase, key in WHEN_PHRASES.items():
        if phrase in s:
            return key
    for tok in s.split():
        if tok in WHEN_WORDS:
            return WHEN_WORDS[tok]
    return None


def followup(s: str, slots: dict, last: dict) -> tuple[str, dict, str] | None:
    """Short follow-ups that reuse the last crop, horizon and intent.
    'and potato?' -> last intent for potato; 'ani?' -> next step; 'aru?' -> pick another crop."""
    last_intent = last.get("intent")
    if not last_intent:
        return None
    toks = [t for t in s.split() if t not in FILLER]
    text = " ".join(toks)
    has_and = bool(set(toks) & FOLLOW_AND) or text.startswith("what about")
    if len(slots.get("crops") or []) == 1 and has_and and len(toks) <= 4 and last_intent in ("PRICE", "FORECAST", "ADVICE", "ARRIVALS"):
        return last_intent, {"horizon": slots.get("horizon") or last.get("horizon")}, "follow-up: same question, new crop"
    if toks and set(toks) <= FOLLOW_AND:
        if last_intent == "FORECAST" and last.get("crop"):
            order = ["d7", "d14", "d21", "d28", "m1", "m2", "m3"]
            h = last.get("horizon") or "d7"
            nxt = order[min(order.index(h) + 1, len(order) - 1)] if h in order else "d7"
            return "FORECAST", {"crop": last["crop"], "horizon": nxt}, "follow-up: next time step"
        if last_intent == "PRICE" and last.get("crop"):
            return "FORECAST", {"crop": last["crop"], "horizon": "d7"}, "follow-up: price then forecast"
        return None
    if toks and set(toks) <= FOLLOW_OTHER | {"bali", "crop", "बाली"}:
        return "OTHER_CROP", {}, "follow-up: another crop"
    return None


def parse(text: str, last_crop: str | None = None, last: dict | None = None) -> NluResult:
    """Full NLU: shorthand, spell correction, slots, classifier, rule boosts, follow-ups. Never raises."""
    raw_norm = normalise(text)
    s, fixes = spell_correct(raw_norm)
    when = find_when(s)
    slots = {"crops": find_crops(s), "horizon": find_horizon(s), "location": find_location(s),
             "qty": find_qty(s), "variant": find_variant(s), "when": when}
    if not slots["horizon"] and when in WHEN_HORIZON and not (set(s.split()) & WEATHER_WORDS):
        slots["horizon"] = WHEN_HORIZON[when] if when in ("next_week", "next_month", "this_week") else None
    slots["crop"] = slots["crops"][0] if slots["crops"] else None
    if fixes:
        slots["corrections"] = [f"{a}->{b}" for a, b in fixes]
    fu = followup(s, slots, last or {})
    if fu:
        intent, extra, rule = fu
        merged = dict(slots)
        merged.update({k: v for k, v in extra.items() if v})
        return NluResult(intent, 0.9, {intent: 0.9}, merged, s, rule)
    probs = intent_model.predict_proba(s)
    toks = set(s.split())
    boosts: dict[str, float] = {}
    if toks & SELL_WORDS:
        boosts["ADVICE"] = 0.92
    elif len(slots["crops"]) >= 2 or (toks & COMPARE_WORDS and slots["crop"]):
        boosts["COMPARE"] = 0.9
    elif slots["horizon"] and (slots["crop"] or last_crop) and not (toks & WEATHER_WORDS):
        boosts["FORECAST"] = 0.92
    elif toks & WEATHER_WORDS and not slots["crop"]:
        boosts["WEATHER"] = 0.9
    elif slots["crop"] and toks & ARRIVAL_WORDS:
        boosts["ARRIVALS"] = 0.9
    elif slots["crop"] and toks & FORECAST_WORDS:
        boosts["FORECAST"] = 0.88
    elif slots["crop"] and len(s.split()) <= 3:
        boosts["PRICE"] = 0.9
    rule = ""
    for k, v in boosts.items():
        if probs.get(k, 0.0) < v:
            probs[k] = v
            rule = f"boost {k}"
    if fixes:
        rule = (rule + "; " if rule else "") + "spelling: " + ", ".join(f"{a}->{b}" for a, b in fixes)
    if not probs:
        return NluResult("UNKNOWN", 0.0, {}, slots, s, "no model")
    intent = max(probs, key=probs.get)
    conf = probs[intent]
    top = dict(sorted(probs.items(), key=lambda kv: -kv[1])[:5])
    if intent in ("PRICE", "FORECAST", "ADVICE", "ARRIVALS") and not slots["crop"] and not last_crop:
        conf = min(conf, 0.6)
    return NluResult(intent, round(conf, 4), {k: round(v, 4) for k, v in top.items()}, slots, s, rule)
