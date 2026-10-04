"""Reply renderers: gather data, fill templates, fit to <= 2 SMS segments. Each returns a Rendered."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app import locations
from app.core import advisor
from app.core.aliases import HORIZON_LABEL, crop_name
from app.core.data import store
from app.core.sms import Part, menu_part
from app.core.templates import (ARRIVALS_BAND_PCT, SAME_CHANGE_PCT, SAME_FORECAST_PCT, TEMPLATES, change_word, finish,
                                fmt_date, menu, money, signed, t, variant_label)
from app.forecast.prep import MONTH_HORIZONS
from app.util import now
from app.weather import outlook

CROPS_PER_PAGE = 7
LOCS_PER_PAGE = 7
P_VALUE, P_CHANGE, P_STATUS, P_DATE, P_WEATHER, P_MENU = 0, 1, 2, 3, 4, 5
STALE_FORECAST_DAYS = 7  # no recent price for this crop (e.g. peas out of season) -> no forecast


@dataclass
class Rendered:
    """A finished reply text plus provenance for the trace."""
    text: str
    dropped: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    model: str | None = None
    status: str | None = None
    options: list = field(default_factory=list)


def _r(parts: list[Part], lang: str, sample: bool, **kw) -> Rendered:
    text, dropped = finish(parts, lang, sample)
    return Rendered(text, dropped, **kw)


def simple(lang: str, *keys: str, sample: bool = False) -> Rendered:
    """Fixed templates, one per line."""
    return _r([Part(t(lang, k), i, k, i == 0) for i, k in enumerate(keys)], lang, sample)


def loc_name(key: str | None, lang: str) -> str:
    """Short district name for SMS."""
    return locations.short_name(locations.get(key or locations.AREA_KEY), lang)


MAIN_NUMBERS = ["1", "2", "3", "4", "5", "6", "9"]


# ---------- onboarding and menus ----------

def welcome(lang: str) -> Rendered:
    """Welcome text."""
    return Rendered(finish([Part(t(lang, "welcome"), 0, "welcome", True)], lang)[0])


def location_options(page: int = 0) -> tuple[list[str], bool]:
    """Location keys for a page (last page ends with boundary_mean = Not sure) and whether more pages exist."""
    keys = [l["key"] for l in locations.selectable()] + [locations.AREA_KEY]
    start = page * LOCS_PER_PAGE
    return keys[start:start + LOCS_PER_PAGE], start + LOCS_PER_PAGE < len(keys)


def location_prompt(lang: str, page: int = 0) -> Rendered:
    """'Where are you?' then one district per line, last 'Not sure'."""
    keys, more = location_options(page)
    items = [(str(i + 1), t(lang, "not_sure") if k == locations.AREA_KEY else loc_name(k, lang)) for i, k in enumerate(keys)]
    if more:
        items.append(("8", t(lang, "more")))
    parts = [Part(t(lang, "loc_q"), 0, "question", True), menu_part(items, 1, "locations", True)]
    return Rendered(finish(parts, lang)[0], options=keys)


def main_menu(lang: str, prefix: str | None = None, sample: bool = False) -> Rendered:
    """Optional first line + MAIN menu."""
    parts = [Part(prefix, 0, "prefix", True)] if prefix else []
    parts.append(menu(lang, "main_opts", MAIN_NUMBERS, 1, True, with_menu=False))
    return _r(parts, lang, sample)


def crop_picker(lang: str, page: int = 0) -> Rendered:
    """'Which crop?' then crops one per line, 8 More, 0 Menu."""
    crops = store().crops()
    pages = max(1, -(-len(crops) // CROPS_PER_PAGE))
    page = page % pages
    sub = crops[page * CROPS_PER_PAGE:(page + 1) * CROPS_PER_PAGE]
    items = [(str(i + 1), crop_name(c, lang)) for i, c in enumerate(sub)]
    if pages > 1:
        items.append(("8", t(lang, "more")))
    items.append(("0", t(lang, "menu")))
    parts = [Part(t(lang, "pick_crop"), 0, "question", True), menu_part(items, 1, "crops", True)]
    return Rendered(finish(parts, lang)[0], options=sub)


def horizon_menu(lang: str, crop: str) -> Rendered:
    """Horizon choices."""
    parts = [Part(t(lang, "pick_h", crop=crop_name(crop, lang)), 0, "question", True), menu(lang, "h_opts", None, 1, True)]
    return Rendered(finish(parts, lang)[0])


def weather_menu(lang: str, loc: str) -> Rendered:
    """Weather sub-menu."""
    parts = [Part(t(lang, "weather_menu", loc=loc_name(loc, lang)), 0, "question", True), menu(lang, "wmenu_opts", None, 1, True)]
    return Rendered(finish(parts, lang)[0])


def lang_menu(lang: str) -> Rendered:
    """Language choices."""
    parts = [Part(t(lang, "lang_menu"), 0, "question", True), menu(lang, "lang_opts", None, 1, True, with_menu=False)]
    return Rendered(finish(parts, lang)[0])


def clarify(lang: str, options: list[tuple[str, str | None]]) -> Rendered:
    """'Did you mean:' then the top two guesses, then 0 Menu."""
    labels = []
    for intent, crop in options:
        key = f"intent_{intent}" if crop or f"intent_{intent}0" not in TEMPLATES[lang] else f"intent_{intent}0"
        labels.append(t(lang, key, crop=crop_name(crop, lang) if crop else ""))
    items = [(str(i + 1), lab) for i, lab in enumerate(labels)] + [("0", t(lang, "menu"))]
    parts = [Part(t(lang, "clarify"), 0, "question", True), menu_part(items, 1, "options", True)]
    return Rendered(finish(parts, lang)[0], options=options)


# ---------- data replies ----------

def _when(d: str, lang: str) -> str:
    return t(lang, "today") if d == now().date().isoformat() else t(lang, "on", d=fmt_date(d, lang))


def _asof(lang: str, offline: bool) -> Part:
    s = store()
    return Part(t(lang, "asof", d=fmt_date(s.today, lang)) if offline and s.today else "", P_DATE, "asof")


RAIN_DAY_MM = 1.0
LIKELY, SOMETIMES = 0.6, 0.3


def weather_line(lang: str, loc: str, offline: bool) -> Part:
    """One short weather line for the farmer's location, in words."""
    try:
        w = outlook.next7(loc, offline)
    except Exception:  # weather must never break a price reply
        return Part("", P_WEATHER, "weather")
    ln = loc_name(loc, lang)
    if w["method"] == "climatology":
        pr = w["days"][0].get("p_rain") if w.get("days") else None
        if pr is None:
            return Part("", P_WEATHER, "weather")
        key = "w_clim_wet" if pr >= LIKELY else "w_clim_some" if pr >= SOMETIMES else "w_clim_dry"
        return Part(t(lang, key, loc=ln), P_WEATHER, "weather")
    mm = w["tomorrow_rain"]
    if mm < RAIN_DAY_MM:
        return Part(t(lang, "w_live_dry", loc=ln), P_WEATHER, "weather")
    return Part(t(lang, "w_live", mm=int(round(mm)), loc=ln), P_WEATHER, "weather")


def price(lang: str, crop: str, loc: str, offline: bool, sample: bool) -> Rendered:
    """Today's price, change in words and a weather line."""
    p = store().price_today(crop)
    name = crop_name(crop, lang)
    follow = menu(lang, "price_opts")
    if not p:
        return _r([Part(t(lang, "no_price", crop=name), 0, "value", True), follow], lang, sample)
    parts = [Part(t(lang, "price_head", crop=name, variant=variant_label(p["origin"], p["size"], lang)), P_VALUE, "head", True)]
    if p["stale"] and p["date"] != store().today:
        parts.append(Part(t(lang, "no_new", when=_when(store().today, lang),
                            p=money(p["price"]), d=fmt_date(p["date"], lang)), P_VALUE, "value", True))
    else:
        parts.append(Part(t(lang, "price", p=money(p["price"]), when=_when(p["date"], lang)), P_VALUE, "value", True))
        if p["prev"]:
            pct = (p["price"] / p["prev"] - 1) * 100
            parts.append(Part(change_word(lang, pct, ("ch_up", "ch_down", "ch_same"), SAME_CHANGE_PCT), P_CHANGE, "change"))
    parts += [_asof(lang, offline), weather_line(lang, loc, offline), follow]
    return _r(parts, lang, sample, sources=["prices", "weather"])


def forecast(lang: str, crop: str, h: str, sample: bool, offline: bool = False) -> Rendered:
    """Forecast range with an honest status label, in plain words."""
    s = store()
    name, hl = crop_name(crop, lang), HORIZON_LABEL[lang][h]
    head = Part(t(lang, "fc_head", crop=name, h=hl), P_VALUE, "head", True)
    f = s.forecast(crop, h)
    follow = menu(lang, "fc_opts")
    if s.run_id is None or f is None:
        return _r([Part(f"{name}", 0, "head", True), Part(t(lang, "not_trained"), 0, "value", True), follow], lang, sample,
                  status="not trained", sources=["forecasts"])
    st = f["status"]
    stale = bool(f["origin_date"] and s.today and
                 (date.fromisoformat(s.today) - date.fromisoformat(f["origin_date"])).days > STALE_FORECAST_DAYS)
    if st == "unavailable" or f["p50"] is None or stale:
        return _r([head, Part(t(lang, "unavailable"), 0, "value", True), follow], lang, sample,
                  status="unavailable", model=f["model_name"], sources=["forecasts"])
    rng = display_range(f)
    if rng is None:
        return _r([head, Part(t(lang, "unavailable"), 0, "value", True), follow], lang, sample,
                  status="unavailable", model=f["model_name"], sources=["forecasts"])
    if st == "pattern only":
        return _r([head, Part(t(lang, "pattern", lo=money(rng[0]), hi=money(rng[1])), 0, "value", True),
                   _asof(lang, offline), follow], lang, sample, status=st, model=f["model_name"], sources=["forecasts"])
    label = "st_seasonal" if h in MONTH_HORIZONS else ("st_reliable" if st == "reliable" else "st_indicative")
    pct = f["pct_change_p50"] or 0.0
    parts = [head, Part(t(lang, "fc_range", lo=money(rng[0]), hi=money(rng[1])), P_VALUE, "value", True),
             Part(change_word(lang, pct, ("fc_up", "fc_down", "fc_same"), SAME_FORECAST_PCT), P_CHANGE, "direction"),
             Part(t(lang, "fc_now", p0=money(f["price0"])), P_DATE, "now"),
             Part(t(lang, label), P_STATUS, "status", True), _asof(lang, offline), follow]
    return _r(parts, lang, sample, status=st, model=f["model_name"], sources=["forecasts"])


ROUND_TO = 5


def display_range(f: dict) -> tuple[int, int] | None:
    """Likely range for farmers: calibrated P25-P75 (right about half the time), clipped to never negative and to
    the crop's historical low and high for that time of year, rounded to the nearest Rs5, and never wider than the
    80% range (P10-P90)."""
    lo, hi = f.get("p25"), f.get("p75")
    if lo is None or hi is None:
        lo, hi = f.get("p10"), f.get("p90")
    if lo is None or hi is None:
        return None
    w_lo, w_hi = f.get("p10") or lo, f.get("p90") or hi
    lo, hi = max(lo, 0.0), hi
    if f.get("band_lo") is not None and f.get("band_hi") is not None and f["band_lo"] < f["band_hi"]:
        lo, hi = max(lo, f["band_lo"]), min(hi, f["band_hi"])
    if lo > hi:  # clipping crossed: keep the calibrated middle
        lo = hi = f.get("p50") or (lo + hi) / 2
    r_lo = int(round(lo / ROUND_TO) * ROUND_TO)
    r_hi = int(round(hi / ROUND_TO) * ROUND_TO)
    r_lo = max(r_lo, int(-(-w_lo // ROUND_TO) * ROUND_TO), 0)   # stay inside the 80% range after rounding
    r_hi = min(r_hi, int((w_hi // ROUND_TO) * ROUND_TO))
    if r_lo > r_hi:
        mid = int(round((f.get("p50") or (lo + hi) / 2) / ROUND_TO) * ROUND_TO)
        r_lo = r_hi = max(mid, 0)
    return r_lo, r_hi


def _rain_word(lang: str, chance: float | None) -> str:
    c = chance or 0.0
    return t(lang, "rain_most" if c >= 0.5 else "rain_some" if c >= 0.2 else "rain_dry")


def weather7(lang: str, loc: str, offline: bool, sample: bool) -> Rendered:
    """Next 7 days for the location."""
    w = outlook.next7(loc, offline)
    ln = loc_name(loc, lang)
    if w["method"] == "climatology":
        parts = [Part(t(lang, "w7c_head", loc=ln), 0, "head", True),
                 Part(t(lang, "w7c_rain", word=_rain_word(lang, w.get("rain_chance")), tot=int(round(w["rain_total"]))), 0, "rain", True),
                 Part(t(lang, "w7c_temp", lo=_i(w["tmax_lo"]), hi=_i(w["tmax_hi"])), 3, "temp"),
                 Part(t(lang, "past_years"), 2, "label", True)]
    else:
        wd = date.fromisoformat(w["wettest_date"]).weekday()
        parts = [Part(t(lang, "w7_head", loc=ln), 0, "head", True),
                 Part(t(lang, "w7_tot", tot=int(round(w["rain_total"]))), 0, "rain", True),
                 Part(t(lang, "w7_most", day=_day(lang, wd), mm=int(round(w["wettest_mm"]))) if w["wettest_mm"] >= 1 else "", 3, "most"),
                 Part(t(lang, "w7_temp", lo=_i(w["tmax_lo"]), hi=_i(w["tmax_hi"])), 3, "temp")]
    parts += [Part(t(lang, "nocoord") if w.get("no_coords") else "", P_STATUS, "nocoord"), menu(lang, "w_opts")]
    return _r(parts, lang, sample, sources=[f"weather:{w['method']}"], status=w["method"])


def _day(lang: str, wd: int) -> str:
    return TEMPLATES[lang]["days"][wd]


def _i(v) -> str:
    return "?" if v is None else str(int(round(v)))


def weeks24(lang: str, loc: str, sample: bool) -> Rendered:
    """Weeks 2-4 outlook (model only if it beat climatology)."""
    w = outlook.weeks24(loc)
    ln = loc_name(loc, lang)
    weeks = w.get("weeks", [])
    if not weeks:
        return simple(lang, "unknown", sample=sample)
    rains = [x["rain_total"] for x in weeks]
    head = Part(t(lang, "w24_head", loc=ln), 0, "head", True)
    if all(r.get("method") == "model" for r in rains):
        body = [Part(t(lang, "w24_model", a=_i(rains[0]["p50"]), b=_i(rains[1]["p50"]), c=_i(rains[2]["p50"])), 0, "value", True),
                Part(t(lang, "st_rough"), 1, "label", True)]
        method = "model"
    else:
        lo = min((r["p10"] for r in rains if r.get("p10") is not None), default=None)
        hi = max((r["p90"] for r in rains if r.get("p90") is not None), default=None)
        mids = [r["p50"] for r in rains if r.get("p50") is not None]
        mid = sum(mids) / len(mids) if mids else 0
        desc = t(lang, "dry" if mid < 5 else "wet" if mid > 40 else "moderate")
        body = [Part(t(lang, "w24_clim", lo=_i(lo), hi=_i(hi), desc=desc), 0, "value", True),
                Part(t(lang, "past_years"), 1, "label", True)]
        method = "climatology"
    return _r([head] + body + [menu(lang, "w_opts", ["1", "2"])], lang, sample,
              sources=[f"weather:{method}"], status=method)


ANOMALY_BAND = 0.2


def months13(lang: str, loc: str, sample: bool) -> Rendered:
    """Season outlook (always climatology)."""
    m = outlook.months13(loc)
    months = [x for x in m.get("months", []) if x.get("p50") is not None]
    if not months:
        return simple(lang, "unknown", sample=sample)
    normal = m.get("normal30_mm") or 0.0
    anom = m.get("anomaly30_mm", 0.0)
    word = "an_same" if abs(anom) <= ANOMALY_BAND * max(normal, 1.0) else ("an_more" if anom > 0 else "an_less")
    parts = [Part(t(lang, "m13_head", loc=loc_name(loc, lang)), 0, "head", True),
             Part(t(lang, "m13_mid", mid=_i(months[0]["p50"])), 0, "value", True),
             Part(t(lang, "m13_last", word=t(lang, word)), 3, "last30"),
             Part(t(lang, "past_years"), 1, "label", True), menu(lang, "w_opts", ["1", "2"])]
    return _r(parts, lang, sample, sources=["weather:climatology"], status="climatology")


def advice(lang: str, crop: str, qty: float | None, loc: str, offline: bool, sample: bool) -> Rendered:
    """Sell/keep hint."""
    a = advisor.advise(crop, qty, loc, offline)
    name = crop_name(crop, lang)
    if a is None:
        return simple(lang, "unknown", sample=sample)
    args = dict(a.reason_args)
    if "pct" in args:
        args["pct"] = signed(args["pct"])
    if "mm" in args:
        args["mm"] = int(round(args["mm"]))
    if "h" in args:
        args["h"] = HORIZON_LABEL[lang][args["h"]]
    args.setdefault("loc", loc_name(loc, lang))
    parts = [Part(t(lang, "adv_head", crop=name, action=t(lang, a.action)), 0, "head", True),
             Part(t(lang, a.reason, **args), 1, "reason", True),
             Part(t(lang, "r_nofc") if a.no_forecast else "", 2, "nofc", True),
             Part(t(lang, f"conf_{a.confidence}"), 2, "conf", True),
             Part(t(lang, "qty", q=money(qty), v=money(a.value_now)) if qty and a.value_now else "", 3, "qty"),
             menu(lang, "adv_opts")]
    return _r(parts, lang, sample, sources=["prices", "forecasts", "weather"], model=a.used_forecast or "rules",
              status=a.confidence)


def arrivals(lang: str, crop: str, sample: bool) -> Rendered:
    """Latest arrivals, compared with the last 7 days in words."""
    a = store().arrivals(crop)
    name = crop_name(crop, lang)
    head = Part(t(lang, "arr_head", crop=name), 0, "head", True)
    follow = menu(lang, "arr_opts")
    if not a:
        return _r([head, Part(t(lang, "arr_none"), 0, "v", True), follow], lang, sample)
    tonnes = a["kg"] / 1000
    tt = f"{tonnes:.0f}" if tonnes >= 10 else f"{tonnes:.1f}"
    parts = [head, Part(t(lang, "arr_val", t=tt, when=_when(a["date"], lang)), 0, "value", True)]
    if a["pct_vs_7d"] is not None:
        parts.append(Part(change_word(lang, a["pct_vs_7d"], ("arr_more", "arr_less", "arr_same"), ARRIVALS_BAND_PCT), 1, "compare"))
    parts.append(follow)
    return _r(parts, lang, sample, sources=["arrivals"])


def compare(lang: str, crops: list[str], sample: bool) -> Rendered:
    """Two crops side by side, or the variants of one crop, one per line."""
    s = store()
    rs = "रु" if lang == "ne" else "Rs"
    items, d = [], s.today
    if len(crops) >= 2:
        for c in crops[:3]:
            p = s.price_today(c)
            if p:
                items.append(f"{crop_name(c, lang)}: {rs}{money(p['price'])}")
                d = p["date"]
    elif crops:
        for v in s.variants(crops[0])[:3]:
            items.append(f"{crop_name(crops[0], lang)}{variant_label(v['origin'], v['size'], lang)}: {rs}{money(v['price'])}")
            d = v["date"]
    if not items:
        return simple(lang, "unknown", sample=sample)
    parts = [Part(t(lang, "cmp_head", d=fmt_date(d, lang)), 0, "head", True), Part("\n".join(items), 0, "value", True),
             menu_part([("0", t(lang, "menu"))], P_MENU)]
    return _r(parts, lang, sample, sources=["prices"])
