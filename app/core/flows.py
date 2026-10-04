"""Conversation state machine: onboarding (NEW -> WELCOME -> ASK_LOCATION -> MAIN), then menu-first with
free-text short-cuts. Pure logic over a farmer dict and a session ctx dict; persistence happens in engine."""
from __future__ import annotations

from dataclasses import dataclass, field

from app import locations
from app.core import nlu, replies
from app.core.aliases import HORIZONS
from app.core.replies import Rendered
from app.core.templates import t

STOP_WORDS = {"stop", "unsubscribe", "banda", "बन्द", "stop all", "रोक"}
START_WORDS = {"start", "subscribe", "resume", "सुरु गर्नुहोस्"}
HELP_WORDS = {"help", "maddat", "मद्दत", "sahayog", "सहयोग", "info"}
MENU_WORDS = {"menu", "0", "मेनु", "main menu", "home"}
NOT_SURE_WORDS = {"not sure", "thaha chhaina", "thaha chaina", "थाहा छैन", "dont know"}
ONBOARDING = ("NEW", "WELCOME", "ASK_LOCATION")
# One-word shortcuts (the simulator quick options send these; farmers can text them too).
SHORTCUTS = {"price": "price", "bhau": "price", "भाउ": "price", "forecast": "forecast", "anuman": "forecast",
             "अनुमान": "forecast", "weather": "weather", "mausam": "weather", "मौसम": "weather", "sell": "advice",
             "hold": "advice", "arrivals": "arrivals", "arrival": "arrivals", "aagaman": "arrivals", "आगमन": "arrivals"}
MAX_INVALID = 3
WELCOME_CAP = 3
CROP_PURPOSE_STATES = {"price": "AFTER_PRICE", "forecast": "PICK_HORIZON", "advice": "AFTER_ADVICE", "arrivals": "AFTER_ARRIVALS"}
WEATHER_SCREENS = {1: "w7", 2: "w24", 3: "m13"}
CROP_INTENTS = {"PRICE", "FORECAST", "ADVICE", "ARRIVALS", "COMPARE"}
NOT_ACTIONABLE = {"UNKNOWN", "SMALLTALK", "STOP", "START"}
PURPOSE_OF = {"PRICE": "price", "FORECAST": "forecast", "ADVICE": "advice", "ARRIVALS": "arrivals"}
INTENT_OF = {"price": "PRICE", "forecast": "FORECAST", "forecast_h": "FORECAST", "advice": "ADVICE", "arrivals": "ARRIVALS"}
LANG_CHOICES = {1: "en", 2: "rn", 3: "ne"}


@dataclass
class FlowOut:
    """What a step produced."""
    r: Rendered
    intent: str
    confidence: float = 1.0
    nlu: dict = field(default_factory=dict)


class Flow:
    """One message step for one farmer. Mutates farmer and ctx in place."""

    def __init__(self, farmer: dict, ctx: dict, offline: bool, sample: bool) -> None:
        self.f = farmer
        self.c = ctx
        self.offline = offline
        self.sample = sample

    @property
    def lang(self) -> str:
        return self.f["lang"]

    @property
    def loc(self) -> str:
        return self.f.get("location") or locations.AREA_KEY

    def go(self, state: str, **kw) -> None:
        self.c["state"] = state
        self.c.update(kw)

    # ---------- entry ----------
    def step(self, raw: str) -> FlowOut:
        s = nlu.normalise(raw)
        g = self._global(s)
        if g:
            return g
        if self.f["onboarding_state"] != "DONE":
            return self._onboarding(s)
        if s in MENU_WORDS:
            return self._main("MENU")
        if s in SHORTCUTS:
            return self._shortcut(SHORTCUTS[s])
        state = self.c.get("state", "MAIN")
        if state == "ASK_LOCATION":
            return self._location_choice(s)
        if s.isdigit():
            return self._number(state, int(s))
        return self._free_text(raw)

    # ---------- global commands ----------
    def _global(self, s: str) -> FlowOut | None:
        if s in STOP_WORDS:
            self.f["subscribed"] = 0
            return FlowOut(replies.simple(self.lang, "stop"), "STOP")
        if s in START_WORDS and self.f["onboarding_state"] == "DONE":
            self.f["subscribed"] = 1
            return FlowOut(replies.simple(self.lang, "start"), "START")
        if s in HELP_WORDS:
            return FlowOut(replies.simple(self.lang, "help"), "HELP")
        code = nlu.lang_command(s)
        if code is None and self.f["onboarding_state"] in ("NEW", "WELCOME") and s in ("en", "ne", "rn", "np"):
            code = "ne" if s == "np" else s
        if code:
            self.f["lang"] = code
            return self._reshow_after_lang()
        return None

    def _reshow_after_lang(self) -> FlowOut:
        ob = self.f["onboarding_state"]
        if ob in ("NEW", "WELCOME"):
            self.f["onboarding_state"] = "WELCOME"
            self.go("WELCOME")
            return FlowOut(replies.welcome(self.lang), "LANG")
        if ob == "ASK_LOCATION" or self.c.get("state") == "ASK_LOCATION":
            return FlowOut(replies.location_prompt(self.lang, self.c.get("loc_page", 0)), "LANG")
        self.go("MAIN")
        return FlowOut(replies.main_menu(self.lang, t(self.lang, "lang_set")), "LANG")

    # ---------- onboarding ----------
    def _onboarding(self, s: str) -> FlowOut:
        ob = self.f["onboarding_state"]
        if ob in ("NEW", "WELCOME"):
            if s in ("1", "suru", "start"):
                return self._ask_location()
            self.c["welcome_count"] = self.c.get("welcome_count", 0) + 1
            self.f["onboarding_state"] = "WELCOME"
            self.go("WELCOME")
            return FlowOut(replies.welcome(self.lang), "START" if ob == "NEW" else "UNKNOWN")
        return self._location_choice(s)

    def _ask_location(self, return_to: str | None = None) -> FlowOut:
        if self.f["onboarding_state"] != "DONE":
            self.f["onboarding_state"] = "ASK_LOCATION"
        self.go("ASK_LOCATION", loc_page=0, invalid_count=0, return_to=return_to)
        return FlowOut(replies.location_prompt(self.lang, 0), "LOCATION")

    def _location_choice(self, s: str) -> FlowOut:
        page = self.c.get("loc_page", 0)
        keys, more = replies.location_options(page)
        key = None
        if s.isdigit():
            n = int(s)
            if n == 0:
                self.c["loc_page"] = 0
                return FlowOut(replies.location_prompt(self.lang, 0), "LOCATION")
            if n == 8 and more:
                self.c["loc_page"] = page + 1
                return FlowOut(replies.location_prompt(self.lang, page + 1), "LOCATION")
            if 1 <= n <= len(keys):
                key = keys[n - 1]
        else:
            key = nlu.find_location(s) or (locations.AREA_KEY if s in NOT_SURE_WORDS else None)
            if key and not locations.get(key):
                key = None
        if key is None:
            self.c["invalid_count"] = self.c.get("invalid_count", 0) + 1
            if self.c["invalid_count"] >= MAX_INVALID:
                return self._save_location(locations.AREA_KEY, default=True)
            return FlowOut(replies.location_prompt(self.lang, page), "LOCATION", 0.0)
        return self._save_location(key)

    def _save_location(self, key: str, default: bool = False) -> FlowOut:
        self.f["location"] = key
        self.f["onboarding_state"] = "DONE"
        self.go("MAIN", loc_page=0, invalid_count=0, return_to=None)
        prefix = t(self.lang, "loc_default") if default else t(self.lang, "loc_saved", loc=replies.loc_name(key, self.lang))
        return FlowOut(replies.main_menu(self.lang, prefix, self.sample), "LOCATION")

    # ---------- menus ----------
    def _main(self, intent: str = "MENU", prefix: str | None = None) -> FlowOut:
        self.go("MAIN", page=0)
        return FlowOut(replies.main_menu(self.lang, prefix, self.sample), intent)

    def _shortcut(self, purpose: str) -> FlowOut:
        """Quick option: open that screen, the same as choosing it from MAIN."""
        if purpose == "weather":
            self.go("WEATHER_MENU")
            return FlowOut(replies.weather_menu(self.lang, self.loc), "WEATHER")
        return self._pick_crop(purpose)

    def _pick_crop(self, purpose: str, page: int = 0) -> FlowOut:
        self.go("PICK_CROP", purpose=purpose, page=page)
        return FlowOut(replies.crop_picker(self.lang, page), {"price": "PRICE", "forecast": "FORECAST",
                                                              "advice": "ADVICE", "arrivals": "ARRIVALS"}[purpose])

    def _number(self, state: str, n: int) -> FlowOut:
        handler = {
            "MAIN": self._n_main, "PICK_CROP": self._n_crop, "PICK_HORIZON": self._n_horizon,
            "AFTER_PRICE": self._n_after_price, "AFTER_FORECAST": self._n_after_forecast,
            "WEATHER_MENU": self._n_weather_menu, "AFTER_WEATHER": self._n_after_weather,
            "AFTER_ADVICE": self._n_after_advice, "AFTER_ARRIVALS": self._n_after_arrivals,
            "LANG_MENU": self._n_lang, "CONFIRM": self._n_confirm,
        }.get(state, self._n_main)
        out = handler(n)
        return out if out else self._invalid(state)

    def _invalid(self, state: str) -> FlowOut:
        if state == "PICK_CROP":
            r = replies.crop_picker(self.lang, self.c.get("page", 0))
        elif state == "PICK_HORIZON" and self.c.get("crop"):
            r = replies.horizon_menu(self.lang, self.c["crop"])
        elif state == "WEATHER_MENU":
            r = replies.weather_menu(self.lang, self.loc)
        elif state == "LANG_MENU":
            r = replies.lang_menu(self.lang)
        else:
            self.go("MAIN")
            r = replies.main_menu(self.lang, t(self.lang, "invalid"), self.sample)
        return FlowOut(r, "UNKNOWN", 0.0)

    def _n_main(self, n: int) -> FlowOut | None:
        if n in (1, 2, 4, 5):
            return self._pick_crop({1: "price", 2: "forecast", 4: "advice", 5: "arrivals"}[n])
        if n == 3:
            self.go("WEATHER_MENU")
            return FlowOut(replies.weather_menu(self.lang, self.loc), "WEATHER")
        if n == 6:
            return self._ask_location(return_to="MAIN")
        if n == 9:
            self.go("LANG_MENU")
            return FlowOut(replies.lang_menu(self.lang), "LANG")
        return None

    def _n_crop(self, n: int) -> FlowOut | None:
        page = self.c.get("page", 0)
        r = replies.crop_picker(self.lang, page)
        if n == 8:
            crops = len(replies.store().crops())
            pages = max(1, -(-crops // replies.CROPS_PER_PAGE))
            return self._pick_crop(self.c.get("purpose", "price"), (page + 1) % pages)
        if 1 <= n <= len(r.options):
            return self._do(self.c.get("purpose", "price"), r.options[n - 1])
        return None

    def _n_horizon(self, n: int) -> FlowOut | None:
        if 1 <= n <= len(HORIZONS) and self.c.get("crop"):
            return self._do("forecast_h", self.c["crop"], HORIZONS[n - 1])
        return None

    def _n_after_price(self, n: int) -> FlowOut | None:
        crop = self.c.get("crop")
        if n == 1 and crop:
            self.go("PICK_HORIZON")
            return FlowOut(replies.horizon_menu(self.lang, crop), "FORECAST")
        if n == 2:
            return self._weather("w7", self.loc)
        if n == 3 and crop:
            return self._do("arrivals", crop)
        if n == 4:
            return self._pick_crop("price")
        return None

    def _n_after_forecast(self, n: int) -> FlowOut | None:
        crop = self.c.get("crop")
        if n == 1 and crop:
            self.go("PICK_HORIZON")
            return FlowOut(replies.horizon_menu(self.lang, crop), "FORECAST")
        if n == 2:
            return self._pick_crop("forecast")
        if n == 3 and crop:
            return self._do("advice", crop)
        return None

    def _n_weather_menu(self, n: int) -> FlowOut | None:
        if n in WEATHER_SCREENS:
            return self._weather(WEATHER_SCREENS[n], self.loc)
        return None

    def _n_after_weather(self, n: int) -> FlowOut | None:
        if n in (1, 2):
            return self._weather("w24" if n == 1 else "m13", self.c.get("wloc") or self.loc)
        return None

    def _n_after_advice(self, n: int) -> FlowOut | None:
        crop = self.c.get("crop")
        if n == 1 and crop:
            self.go("PICK_HORIZON")
            return FlowOut(replies.horizon_menu(self.lang, crop), "FORECAST")
        if n == 2:
            return self._weather("w7", self.loc)
        return None

    def _n_after_arrivals(self, n: int) -> FlowOut | None:
        crop = self.c.get("crop")
        if n == 1 and crop:
            return self._do("price", crop)
        if n == 2:
            return self._pick_crop("arrivals")
        return None

    def _n_lang(self, n: int) -> FlowOut | None:
        if n in LANG_CHOICES:
            self.f["lang"] = LANG_CHOICES[n]
            return self._main("LANG", t(self.lang, "lang_set"))
        return None

    def _n_confirm(self, n: int) -> FlowOut | None:
        opts = self.c.get("confirm") or []
        if 1 <= n <= len(opts):
            intent, crop = opts[n - 1]
            return self._execute(intent, {"crop": crop, "crops": [crop] if crop else [], "horizon": None,
                                          "location": None, "qty": None}, 0.75)
        return None

    # ---------- actions ----------
    def _do(self, purpose: str, crop: str, horizon: str | None = None, qty: float | None = None) -> FlowOut:
        self.c["crop"] = crop
        self.c["last_intent"] = INTENT_OF.get(purpose, self.c.get("last_intent"))
        if purpose == "price":
            self.go("AFTER_PRICE")
            return FlowOut(replies.price(self.lang, crop, self.loc, self.offline, self.sample), "PRICE")
        if purpose == "forecast":
            self.go("PICK_HORIZON")
            return FlowOut(replies.horizon_menu(self.lang, crop), "FORECAST")
        if purpose == "forecast_h":
            self.go("AFTER_FORECAST", horizon=horizon)
            return FlowOut(replies.forecast(self.lang, crop, horizon, self.sample, self.offline), "FORECAST")
        if purpose == "advice":
            self.go("AFTER_ADVICE")
            return FlowOut(replies.advice(self.lang, crop, qty, self.loc, self.offline, self.sample), "ADVICE")
        self.go("AFTER_ARRIVALS")
        return FlowOut(replies.arrivals(self.lang, crop, self.sample), "ARRIVALS")

    def _weather(self, screen: str, loc: str) -> FlowOut:
        self.go("AFTER_WEATHER", wloc=loc, last_intent="WEATHER")
        if screen == "w7":
            r = replies.weather7(self.lang, loc, self.offline, self.sample)
        elif screen == "w24":
            r = replies.weeks24(self.lang, loc, self.sample)
        else:
            r = replies.months13(self.lang, loc, self.sample)
        return FlowOut(r, "WEATHER")

    # ---------- free text ----------
    def _free_text(self, raw: str) -> FlowOut:
        last = {"intent": self.c.get("last_intent"), "crop": self.c.get("crop"), "horizon": self.c.get("horizon")}
        res = nlu.parse(raw, self.c.get("crop"), last)
        info = {"probs": res.probs, "slots": res.slots, "normalised": res.text, "rule": res.rule}
        if res.intent == "OTHER_CROP":
            out = self._pick_crop(PURPOSE_OF.get(self.c.get("last_intent"), "price"))
        elif res.confidence >= nlu.ACT:
            out = self._execute(res.intent, res.slots, res.confidence)
        elif res.confidence >= nlu.ASK and res.intent not in NOT_ACTIONABLE:
            crop = res.slots.get("crop") or self.c.get("crop")
            guesses = [i for i in res.probs if i not in NOT_ACTIONABLE][:2]
            opts = [(i, crop if i in CROP_INTENTS else None) for i in guesses]
            self.go("CONFIRM", confirm=opts)
            out = FlowOut(replies.clarify(self.lang, opts), "CLARIFY", res.confidence)
        else:
            out = self._main("UNKNOWN", t(self.lang, "unknown"))
        out.nlu = info
        out.confidence = res.confidence
        return out

    def _execute(self, intent: str, slots: dict, conf: float) -> FlowOut:
        crop = slots.get("crop") or self.c.get("crop")
        if intent == "PRICE":
            return self._do("price", crop) if crop else self._pick_crop("price")
        if intent == "FORECAST":
            if not crop:
                return self._pick_crop("forecast")
            return self._do("forecast_h", crop, slots.get("horizon") or self.c.get("horizon") or "d7")
        if intent == "ADVICE":
            return self._do("advice", crop, qty=slots.get("qty")) if crop else self._pick_crop("advice")
        if intent == "ARRIVALS":
            return self._do("arrivals", crop) if crop else self._pick_crop("arrivals")
        if intent == "COMPARE":
            crops = slots.get("crops") or ([crop] if crop else [])
            if not crops:
                return self._pick_crop("price")
            self.go("MAIN")
            return FlowOut(replies.compare(self.lang, crops, self.sample), "COMPARE")
        if intent == "WEATHER":
            loc = slots.get("location") if slots.get("location") and locations.get(slots["location"]) else self.loc
            h = slots.get("horizon")
            screen = "m13" if h in ("m1", "m2", "m3") else "w24" if h in ("d14", "d21", "d28") else "w7"
            return self._weather(screen, loc)
        if intent == "LOCATION":
            key = slots.get("location")
            if key and locations.get(key):
                return self._save_location(key)
            return self._ask_location(return_to="MAIN")
        if intent == "LANG":
            self.go("LANG_MENU")
            return FlowOut(replies.lang_menu(self.lang), "LANG")
        if intent == "HELP":
            return FlowOut(replies.simple(self.lang, "help"), "HELP")
        if intent == "STOP":
            self.f["subscribed"] = 0
            return FlowOut(replies.simple(self.lang, "stop"), "STOP")
        if intent == "START":
            self.f["subscribed"] = 1
            return FlowOut(replies.simple(self.lang, "start"), "START")
        if intent == "SMALLTALK":
            return self._main("SMALLTALK", t(self.lang, "hello"))
        if intent == "MENU":
            return self._main("MENU")
        return self._main("UNKNOWN", t(self.lang, "unknown"))

