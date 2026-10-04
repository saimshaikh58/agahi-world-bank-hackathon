"""Generate data/nlu_training.jsonl: at least 200 varied examples per intent per language (en, rn, ne).
Deterministic (seeded). Slots come from the alias lists. Augmentation: typos, dropped vowels, repeated
letters, SMS shorthand, mixed English and Roman Nepali, filler words and casual full sentences.
Run: python scripts/make_nlu_data.py"""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import aliases  # noqa: E402

PER_CELL = 220
MAX_TRIES = 30000
SEED = 7

T = {
    "PRICE": {
        "en": ["{c} price", "price of {c}", "how much is {c} today", "{c} rate today", "what is the {c} price",
               "{c} price today", "today {c} rate", "{c} price please", "current price of {c}", "{c} cost per kg",
               "kalimati {c} price", "{c} wholesale price", "whats {c} going for", "{c} how much", "rate of {c} in kalimati",
               "tell me {c} price", "how much for 1 kg {c}", "{c} today", "what does {c} sell for", "{c} market rate"],
        "rn": ["{c} ko bhau", "{c} kati ho", "aaja {c} ko mol", "{c} bhau kati", "{c} ko rate", "{c} kati parcha",
               "aja {c} ko bhau", "{c} ko mol kati", "kalimati ma {c} kati", "{c} kilo ko kati", "{c} bhau",
               "{c} ko bhaau kati cha", "aaja {c} ko rate kati ho", "{c} ko price kati", "{c} kati ma bikdai cha",
               "kalimati ma aaja {c} kasto rate cha", "{c} ko aajko bhau", "{c} kg ko kati", "{c} rate kati ho hajur",
               "malai {c} ko bhau bhannus"],
        "ne": ["{c} को भाउ", "आज {c} कति", "{c} को मूल्य", "{c} कति हो", "{c} को भाउ कति छ", "कालीमाटीमा {c} कति",
               "{c} प्रति किलो कति", "आजको {c} भाउ", "{c} को दर", "{c} कति पर्छ", "{c} को आजको भाउ कति हो",
               "{c} किलोको कति", "कालीमाटीमा आज {c} को भाउ", "{c} को रेट", "{c} कतिमा बिक्दैछ"],
    },
    "FORECAST": {
        "en": ["{c} in {n} days", "{c} price next week", "will {c} price go up", "{c} forecast", "{c} next month",
               "{c} price in {w} weeks", "will {c} get cheaper", "{c} price after {n} days", "predict {c} price",
               "{c} {m} months outlook", "future price of {c}", "is {c} going down", "what will {c} cost next week",
               "{c} price trend", "{c} after {m} month", "will {c} go up or down", "{c} {n} days later",
               "expected {c} price next month", "{c} price coming weeks", "should {c} price rise soon"],
        "rn": ["{c} {n} din", "{c} {w} hapta pachi", "{c} ko bhau badhcha", "{c} ghatcha", "aaglo mahina {c}",
               "{c} bhau ke hola", "{c} {m} mahina pachi", "{c} ko bhau ghatla", "{c} {n} din pachi kati hola",
               "{c} aaglo hapta", "{c} forecast", "{c} badhla ki ghatla", "next hapta {c} kasto hola",
               "{c} ko bhau aaglo hapta kati hola", "{c} {w} hapta ma kati pugla", "arko mahina {c} mahango hola",
               "{c} sasto hola ki", "{c} ko bhau kahile badhcha", "{c} anuman", "{c} ko aaune din ko bhau"],
        "ne": ["{c} {n} दिन पछि", "{c} को भाउ बढ्छ", "अर्को महिना {c}", "{c} पूर्वानुमान", "{c} {w} हप्ता पछि",
               "{c} को भाउ घट्छ", "{c} {m} महिनामा कति", "आगामी हप्ता {c}", "{c} भाउ के होला", "{c} {n} दिनमा",
               "अर्को हप्ता {c} को भाउ कति होला", "{c} सस्तो होला कि", "{c} महँगो होला", "{c} को भाउ अनुमान",
               "{c} आउने दिनमा कति"],
    },
    "WEATHER": {
        "en": ["weather", "rain tomorrow", "will it rain", "weather in {l}", "next month rain", "rain this week",
               "temperature today", "weather forecast", "how much rain", "is it going to rain in {l}",
               "weather next week", "rain outlook", "is tomorrow dry", "how hot will it be", "rain in {l} tomorrow",
               "any rain coming", "weather for {l}", "will it be sunny", "season rain outlook", "how is the weather"],
        "rn": ["mausam", "pani parcha", "bholi pani parcha", "{l} ma mausam", "barsha kati", "aaglo hapta pani",
               "mausam kasto cha", "aaja pani parcha ki", "{l} ko mausam", "garmi kati", "aaglo mahina barsha",
               "pani parne ho", "bholi paani parchha", "{l} ma bholi paani parchha ki", "yo hapta paani kati",
               "ghaam lagcha ki", "aaja mausam kasto", "parsi pani parla", "jado kati cha", "mausam bhannus"],
        "ne": ["मौसम", "भोलि पानी पर्छ", "{l} मा मौसम", "वर्षा", "पानी पर्छ कि", "आजको मौसम", "अर्को हप्ता वर्षा",
               "तापक्रम कति", "{l} को मौसम", "मौसम कस्तो छ", "भोलि {l} मा पानी पर्छ", "यो हप्ता वर्षा कति",
               "घाम लाग्छ कि", "पर्सि पानी पर्ला", "अर्को महिना वर्षा"],
    },
    "ADVICE": {
        "en": ["should i sell {c}", "sell {c} {q}kg", "sell or hold {c}", "when to sell {c}", "is it a good time to sell {c}",
               "should i wait to sell {c}", "hold {c} or sell", "i have {q} kg {c} sell now", "sell {c} today or wait",
               "keep {c} or sell", "best time to sell {c}", "should i keep my {c}", "{q}kg {c} sell?", "can i sell {c} now"],
        "rn": ["becham {c} {q}kg", "{c} bechne ki rakhne", "aaja {c} bechu", "{c} kahile bechne", "{c} bechnu parcha",
               "{c} {q} kg cha becham", "{c} rakhu ki bechu", "becham {c}", "{c} becham ki rakhum", "alu becham ki rakhum",
               "mero {q} kg {c} cha bechu ki", "{c} aaja bechda thik", "{c} rakhda ramro ki bechda", "{c} kahile bechda ramro"],
        "ne": ["{c} बेचौं", "{c} बेच्ने कि राख्ने", "आज {c} बेच्ने", "{c} कहिले बेच्ने", "{q} केजी {c} बेच्ने",
               "{c} राख्ने कि", "{c} बेचु कि", "मसँग {q} केजी {c} छ बेचौं कि", "{c} आज बेच्दा ठिक", "{c} कहिले बेच्दा राम्रो"],
    },
    "ARRIVALS": {
        "en": ["{c} arrivals", "how much {c} came today", "supply of {c}", "{c} supply today", "{c} arrival in market",
               "how many kg of {c} arrived", "{c} market supply", "{c} coming to kalimati", "how much {c} in market",
               "{c} stock in market", "is there lots of {c} in market", "{c} arrival today"],
        "rn": ["{c} kati aayo", "{c} aagaman", "bazar ma {c} kati", "{c} kati aaipugyo", "aaja {c} kati aayo",
               "{c} ko aagaman", "{c} supply kati", "kalimati ma {c} kati aayo", "{c} dherai aayo ki",
               "{c} ko aawak kati", "bazar ma {c} ko aagaman kasto"],
        "ne": ["{c} आगमन", "{c} कति आयो", "बजारमा {c} कति", "आज {c} कति आयो", "{c} को आगमन",
               "कालीमाटीमा {c} कति आयो", "{c} धेरै आयो कि", "{c} को आवक"],
    },
    "COMPARE": {
        "en": ["{c} vs {c2}", "compare {c} and {c2}", "indian vs nepali {c}", "{c} or {c2} which is better price",
               "compare {c} prices", "{c} versus {c2}", "which is costlier {c} or {c2}", "{c} and {c2} price",
               "difference between {c} and {c2}"],
        "rn": ["{c} ra {c2} tulana", "nepali ra indian {c}", "{c} vs {c2}", "{c} ki {c2} kun mahango", "{c} tulana",
               "{c} ra {c2} ko bhau", "{c} ra {c2} ma kun sasto", "indian {c} ra nepali {c} ko pharak"],
        "ne": ["{c} र {c2} तुलना", "नेपाली र भारतीय {c}", "{c} कि {c2} कुन महँगो", "{c} तुलना", "{c} र {c2} को भाउ",
               "{c} र {c2} मा कुन सस्तो"],
    },
    "LOCATION": {
        "en": ["change location", "my location", "i am in {l}", "set location {l}", "update my place", "location",
               "change my district", "i moved to {l}", "i live in {l}", "my farm is in {l}", "set my area"],
        "rn": ["thau badalnu", "ma {l} ma chhu", "mero thau", "thau", "thau change", "mero jilla {l}", "thau pherne",
               "ma {l} tira baschhu", "mero khet {l} ma cha", "thau update garnu"],
        "ne": ["ठाउँ बदल्नु", "म {l} मा छु", "मेरो ठाउँ", "ठाउँ", "जिल्ला बदल्ने", "मेरो जिल्ला {l}", "मेरो खेत {l} मा छ"],
    },
    "LANG": {
        "en": ["language", "change language", "english please", "switch language", "in english", "english",
               "can you reply in english", "change to nepali", "different language"],
        "rn": ["bhasha", "bhasa badalnu", "bhasa", "nepali ma", "roman ma", "bhasha pherne", "nepali ma lekhnus",
               "english ma pathaunus", "bhasa change"],
        "ne": ["भाषा", "भाषा बदल्नु", "नेपालीमा", "भाषा परिवर्तन", "नेपालीमा लेख्नुहोस्", "अंग्रेजीमा पठाउनुहोस्"],
    },
    "HELP": {
        "en": ["help", "how does this work", "what can you do", "info", "instructions", "how to use", "i need help",
               "i dont understand", "what is this", "how do i ask price"],
        "rn": ["maddat", "sahayog", "kasari chalaune", "maddat chahiyo", "k garna milcha", "jankari", "bujhina kasari",
               "yo k ho", "kasari sodhne"],
        "ne": ["मद्दत", "सहयोग", "कसरी चलाउने", "जानकारी", "के गर्न मिल्छ", "बुझिनँ कसरी", "यो के हो"],
    },
    "MENU": {
        "en": ["menu", "main menu", "back", "home", "options", "show menu", "go back", "start over", "show options"],
        "rn": ["menu", "suru ma", "pheri menu", "mukhya menu", "menu dekhau", "pachadi", "menu pathau", "suru dekhi"],
        "ne": ["मेनु", "सूची", "मुख्य मेनु", "पछाडि", "मेनु देखाउ", "सुरुदेखि"],
    },
    "STOP": {
        "en": ["stop", "unsubscribe", "no more sms", "stop messages", "cancel", "quit", "stop alerts", "dont send me sms"],
        "rn": ["banda", "na pathaunus", "banda garnus", "sms banda", "pathauna banda", "alert banda", "aru na pathau"],
        "ne": ["बन्द", "नपठाउनुहोस्", "बन्द गर्नुहोस्", "एसएमएस बन्द", "सूचना बन्द", "अब नपठाउनु"],
    },
    "START": {
        "en": ["start", "subscribe", "resume", "start again", "join", "sign up", "start alerts", "send me alerts again"],
        "rn": ["suru", "feri suru", "suru garnus", "jodnus", "pheri pathaunus", "alert suru", "feri pathau"],
        "ne": ["सुरु", "फेरि सुरु", "सुरु गर्नुहोस्", "जोड्नुहोस्", "सूचना सुरु", "फेरि पठाउनु"],
    },
    "SMALLTALK": {
        "en": ["hi", "hello", "thanks", "thank you", "good morning", "ok", "nice", "good night", "hey there", "great thanks",
               "how are you", "good job"],
        "rn": ["namaste", "dhanyabad", "huncha", "thik cha", "namaskar", "ramro", "sanchai hunuhuncha", "dhanyabaad hajur",
               "la thik", "khub ramro"],
        "ne": ["नमस्ते", "धन्यवाद", "ठिक छ", "नमस्कार", "राम्रो", "हुन्छ", "सन्चै हुनुहुन्छ"],
    },
    "UNKNOWN": {
        "en": ["what is the cricket score", "asdf", "my cow is sick", "bus timing", "who are you dating", "xyz",
               "play music", "loan please", "football news", "where is the bank", "qwerty", "send money",
               "recharge my phone", "tell me a joke", "lottery result", "movie tonight"],
        "rn": ["loan chahiyo", "bus kati baje", "gai birami cha", "khana khayau", "phone recharge", "kta kta",
               "mobile bigryo", "paisa pathau", "jagga kinne", "hjkl", "cricket score", "gana bajau", "bank kaha cha"],
        "ne": ["ऋण चाहियो", "बस कति बजे", "गाई बिरामी छ", "खाना खायौ", "रिचार्ज", "जग्गा किन्ने", "पैसा पठाउ",
               "क्रिकेट स्कोर", "गीत बजाउ", "बैंक कहाँ छ"],
    },
}
FILLERS = {"en": ["", "", "", "pls", "please", "hey", "ok", "sir", "bro", "hello", "quick"],
           "rn": ["", "", "", "hajur", "kripaya", "dai", "la", "ni", "bhai", "ali", "hai", "ke"],
           "ne": ["", "", "", "कृपया", "हजुर", "दाइ", "है", "ल", "अब", "बहिनी", "सर", "ए"]}
SHORT = {"en": {"please": "pls", "what": "wat", "tomorrow": "tmrw", "today": "2day", "price": "prc", "you": "u",
                "for": "4", "to": "2", "how": "hw", "much": "mch", "rate": "rt", "weather": "wthr", "and": "n"},
         "rn": {"kati": "kti", "bhau": "bhu", "chha": "cha", "hunchha": "huncha", "parchha": "parcha", "mausam": "msm",
                "aaja": "aj", "bholi": "bholy", "pachi": "pachhi", "garnus": "grnus", "ko": "ko", "hapta": "hpta"}}
MIX = {"rn": {"bhau": "price", "kati": "how much", "aaja": "today", "bholi": "tomorrow", "mausam": "weather",
              "hapta": "week", "mahina": "month"},
       "en": {"price": "bhau", "today": "aaja", "tomorrow": "bholi", "week": "hapta", "how much": "kati"}}
VOWELS = "aeiou"


def _typo(s: str, rng: random.Random) -> str:
    if len(s) < 5:
        return s
    i = rng.randrange(1, len(s) - 1)
    op = rng.choice(["drop", "dup", "swap"])
    if op == "drop":
        return s[:i] + s[i + 1:]
    if op == "dup":
        return s[:i] + s[i] + s[i:]
    return s[:i - 1] + s[i] + s[i - 1] + s[i + 1:]


def _drop_vowels(s: str, rng: random.Random) -> str:
    words = s.split()
    k = rng.randrange(len(words))
    w = words[k]
    if len(w) > 4:
        words[k] = w[0] + "".join(ch for ch in w[1:] if ch not in VOWELS or rng.random() < 0.5)
    return " ".join(words)


def _repeat(s: str, rng: random.Random) -> str:
    words = s.split()
    k = rng.randrange(len(words))
    w = words[k]
    if w and w[-1].isalpha():
        words[k] = w + w[-1] * rng.randint(1, 3)
    return " ".join(words)


def _sub(s: str, table: dict, rng: random.Random) -> str:
    for a, b in table.items():
        if rng.random() < 0.5:
            s = re.sub(rf"\b{re.escape(a)}\b", b, s)
    return s


def _augment(text: str, lang: str, rng: random.Random) -> str:
    if lang != "ne":
        r = rng.random()
        if r < 0.25:
            text = _typo(text, rng)
        elif r < 0.40:
            text = _drop_vowels(text, rng)
        elif r < 0.50:
            text = _repeat(text, rng)
        if rng.random() < 0.35:
            text = _sub(text, SHORT[lang], rng)
        if rng.random() < 0.2:
            text = _sub(text, MIX[lang], rng)
        if rng.random() < 0.2:
            text = text.upper() if rng.random() < 0.3 else text.capitalize()
    f = rng.choice(FILLERS[lang])
    if f:
        text = f"{f} {text}" if rng.random() < 0.5 else f"{text} {f}"
    if rng.random() < 0.2:
        text += rng.choice(["?", "??", "!", "."]) if lang != "ne" else rng.choice(["?", "।", "!"])
    return text


def _crop_word(lang: str, rng: random.Random) -> str:
    crop = rng.choice(list(aliases.CROP_ALIASES))
    al = aliases.CROP_ALIASES[crop]
    if lang == "ne":
        cands = [a for a in al if any("ऀ" <= ch <= "ॿ" for ch in a)]
        if rng.random() < 0.1:
            cands = [a for a in al if a.isascii()]
    else:
        cands = [a for a in al if a.isascii()]
    return rng.choice(cands or [aliases.crop_name(crop, lang)])


def _loc_word(lang: str, rng: random.Random) -> str:
    key = rng.choice(list(aliases.LOCATION_ALIASES))
    al = aliases.LOCATION_ALIASES[key]
    cands = [a for a in al if (not a.isascii()) == (lang == "ne")]
    return rng.choice(cands or al)


def generate() -> list[dict]:
    """Build the full deduplicated example list."""
    rng = random.Random(SEED)
    out = []
    for intent, by_lang in T.items():
        for lang, templates in by_lang.items():
            seen: set[str] = set()
            tries = 0
            while len(seen) < PER_CELL and tries < MAX_TRIES:
                tries += 1
                text = rng.choice(templates).format(
                    c=_crop_word(lang, rng), c2=_crop_word(lang, rng), l=_loc_word(lang, rng),
                    n=rng.choice([3, 5, 7, 10, 14, 21, 28]), w=rng.choice([1, 2, 3, 4]),
                    m=rng.choice([1, 2, 3]), q=rng.choice([50, 100, 200, 300, 500, 1000]))
                seen.add(_augment(text, lang, rng).strip())
            out.extend({"text": s, "intent": intent, "lang": lang} for s in sorted(seen))
    return out


def main() -> None:
    rows = generate()
    path = ROOT / "data" / "nlu_training.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Wrote {len(rows)} examples to {path}")


if __name__ == "__main__":
    main()
