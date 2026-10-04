"""Alias dictionaries: crops, variants, horizons, locations in English, Roman Nepali and Devanagari.
Nepali and Roman Nepali entries should be reviewed by a native speaker before a real pilot."""
from __future__ import annotations

import json
from pathlib import Path

from app.config import DATA_DIR

ALIAS_OVERRIDES = DATA_DIR / "alias_overrides.json"
NE_DIGITS = "०१२३४५६७८९"
TO_ASCII = str.maketrans(NE_DIGITS, "0123456789")
TO_NE = str.maketrans("0123456789", NE_DIGITS)

CROP_ORDER = ["tomato", "potato", "onion_dry", "cauliflower", "cabbage", "carrot", "radish",
              "eggplant", "beans", "peas", "bitter_gourd", "okra", "pumpkin"]

# Display names per language
CROP_NAMES = {
    "tomato": ("Tomato", "Golbheda", "गोलभेडा"),
    "potato": ("Potato", "Alu", "आलु"),
    "onion_dry": ("Onion", "Pyaj", "प्याज"),
    "cauliflower": ("Cauliflower", "Kauli", "काउली"),
    "cabbage": ("Cabbage", "Banda", "बन्दा"),
    "carrot": ("Carrot", "Gajar", "गाजर"),
    "radish": ("Radish", "Mula", "मूला"),
    "eggplant": ("Eggplant", "Bhanta", "भन्टा"),
    "beans": ("Beans", "Simi", "सिमी"),
    "peas": ("Peas", "Matar", "मटर"),
    "bitter_gourd": ("Bitter gourd", "Karela", "करेला"),
    "okra": ("Okra", "Bhindi", "भिन्डी"),
    "pumpkin": ("Pumpkin", "Pharsi", "फर्सी"),
}

CROP_ALIASES = {
    "tomato": ["tomato", "tomatoes", "tamatar", "tamatur", "golbheda", "golvheda", "gol bheda", "golbeda",
               "golbhenda", "golbheda", "golveda", "golbhyada", "golbedha", "गोलभेडा", "गोलभेँडा", "टमाटर"],
    "potato": ["potato", "potatoes", "alu", "aalu", "aloo", "aaloo", "alo", "आलु", "आलू"],
    "onion_dry": ["onion", "onions", "pyaj", "pyaaj", "pyaz", "piyaj", "pyāj", "प्याज", "प्याज़"],
    "cauliflower": ["cauliflower", "cauli", "kauli", "cauly", "kaauli", "phulkopi", "phool gobi", "gobi",
                    "काउली", "कौली", "फूलकोपी"],
    "cabbage": ["cabbage", "banda", "bandakopi", "banda kopi", "bandha", "patta gobi", "बन्दा", "बन्दाकोपी"],
    "carrot": ["carrot", "carrots", "gajar", "gajor", "gajjar", "गाजर"],
    "radish": ["radish", "mula", "moola", "mulaa", "mooli", "muli", "मूला", "मुला"],
    "eggplant": ["eggplant", "brinjal", "aubergine", "bhanta", "bhanta", "bhantaa", "baigun", "baingan",
                 "भन्टा", "भण्टा", "बैगुन"],
    "beans": ["beans", "bean", "simi", "seemi", "ghiu simi", "bodi", "भटमास", "सिमी", "बोडी"],
    "peas": ["peas", "pea", "matar", "matarkosa", "kerau", "मटर", "मटरकोशा", "केराउ"],
    "bitter_gourd": ["bitter gourd", "bittergourd", "karela", "karelaa", "tito karela", "करेला", "तितो करेला"],
    "okra": ["okra", "ladyfinger", "lady finger", "bhindi", "bhendi", "bhindee", "भिन्डी", "भिण्डी"],
    "pumpkin": ["pumpkin", "pharsi", "farsi", "phersi", "pharshi", "kaddu", "फर्सी", "कद्दु"],
}

VARIANT_WORDS = {
    "indian": ["indian", "bharatiya", "bharatiy", "india", "भारतीय"],
    "nepali": ["nepali", "nepal", "local", "lokal", "sthaniya", "नेपाली", "लोकल", "स्थानीय"],
    "large": ["thulo", "big", "large", "ठूलो", "ठुलो"],
    "small": ["sano", "small", "सानो"],
}

HORIZON_UNITS = {
    "day": ["din", "day", "days", "dina", "दिन"],
    "week": ["hapta", "week", "weeks", "wk", "hafta", "haptaa", "हप्ता"],
    "month": ["mahina", "month", "months", "mahinaa", "mahena", "महिना"],
}
HORIZONS = ["d7", "d14", "d21", "d28", "m1", "m2", "m3"]
HORIZON_DAYS = {"d7": 7, "d14": 14, "d21": 21, "d28": 28, "m1": 30, "m2": 60, "m3": 90}
HORIZON_LABEL = {
    "en": {"d7": "7 days", "d14": "14 days", "d21": "21 days", "d28": "28 days", "m1": "1 month", "m2": "2 months", "m3": "3 months"},
    "rn": {"d7": "7 din", "d14": "14 din", "d21": "21 din", "d28": "28 din", "m1": "1 mahina", "m2": "2 mahina", "m3": "3 mahina"},
    "ne": {"d7": "7 दिन", "d14": "14 दिन", "d21": "21 दिन", "d28": "28 दिन", "m1": "1 महिना", "m2": "2 महिना", "m3": "3 महिना"},
}

LOCATION_ALIASES = {
    "kathmandu_valley": ["kathmandu", "ktm", "kathmandu valley", "upatyaka", "lalitpur", "bhaktapur", "काठमाडौं", "काठमाण्डौ", "उपत्यका"],
    "kavre_dhulikhel": ["kavre", "kabhre", "kavrepalanchok", "dhulikhel", "banepa", "काभ्रे", "धुलिखेल"],
    "nuwakot_bidur": ["nuwakot", "nuwakote", "bidur", "trishuli", "नुवाकोट", "बिदुर"],
    "dhading_besi": ["dhading", "dhadhing", "dhading besi", "धादिङ", "धादिङबेंसी"],
    "sindhupalchok": ["sindhupalchok", "sindhupalchowk", "sindhu", "chautara", "सिन्धुपाल्चोक", "चौतारा"],
    "makwanpur_hetauda": ["makwanpur", "makawanpur", "hetauda", "hetaunda", "मकवानपुर", "हेटौंडा"],
}

LANG_WORDS = {"en": ["en", "english", "eng"], "rn": ["rn", "roman", "roman nepali"], "ne": ["ne", "np", "nepali", "नेपाली"]}


def crop_name(crop: str, lang: str) -> str:
    """Crop display name in a language."""
    names = CROP_NAMES.get(crop)
    if not names:
        return crop.replace("_", " ").title()
    return names[{"en": 0, "rn": 1, "ne": 2}[lang]]


def load_overrides() -> dict[str, str]:
    """User-added aliases from the quality queue: alias -> crop."""
    if not ALIAS_OVERRIDES.exists():
        return {}
    try:
        data = json.loads(ALIAS_OVERRIDES.read_text(encoding="utf-8"))
        return {str(k).lower(): str(v) for k, v in data.items() if v in CROP_NAMES}
    except (ValueError, OSError):
        return {}


def save_override(alias: str, crop: str, path: Path | None = None) -> None:
    """Add one alias override."""
    p = path or ALIAS_OVERRIDES
    data = load_overrides()
    data[alias.strip().lower()] = crop
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
