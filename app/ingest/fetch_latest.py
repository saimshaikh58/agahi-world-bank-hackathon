"""Fetch new Kalimati days (prices + arrivals) and append them to the database.

The parsing code (text helpers, crop rules, units, response_to_df, standardize_*, Fetcher, enrich) is the
owner's Colab scraper, kept as it was: it fetches the same pages in the same way. Changes for running inside
the app: no pip install / Google Drive, shorter timeouts, fewer retries, the detected date form is remembered
in the database, and days are fetched in small chunks with a time budget.

After new rows are stored, today's forecasts are recomputed with the EXISTING trained models (no retraining),
the forecast ledger is updated and the weather outlook is refreshed. On any failure the old data stays.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import logging
import re
import threading
import time
from typing import Any, Callable
from urllib.parse import urljoin

import numpy as np
import pandas as pd

from app import db
from app.util import now, now_iso

log = logging.getLogger("agahi.fetch")

BASE = "https://kalimatimarket.gov.np"
PAGES = {"prices": BASE + "/price", "arrivals": BASE + "/daily-arrivals"}
TIMEOUT = 8                  # seconds per request (serverless functions have a short time limit)
TRIES = 2
DELAY = (0.3, 0.8)
CHUNK_DAYS = 5               # most days fetched in one run
MAX_BACK_DAYS = 30           # never try to catch up more than this many days in one go
BUDGET_S = 20.0              # stop starting new days after this many seconds

# ----------------------------- TEXT HELPERS (owner's code) -------------------
DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_VARIANTS = str.maketrans({"ू": "ु", "ी": "ि", "ण": "न"})


def norm(s):
    """Lowercase, Nepali digits -> ascii, merge common spelling variants."""
    s = str(s).lower().translate(DEV_DIGITS)
    s = re.sub("[‌‍ँ]", "", s)
    return s.translate(_VARIANTS).strip()


def to_num(series):
    s = series.astype(str).str.translate(DEV_DIGITS).str.replace(",", "", regex=False)
    return pd.to_numeric(s.str.extract(r"(-?\d+\.?\d*)")[0], errors="coerce")


# ----------------------------- CROP RULES (owner's code) ---------------------
_CROPS = {
    "tomato":      (["गोलभेडा", "tomato"], []),
    "potato":      (["आलु", "आलू", "potato"], ["बखडा", "बखरा", "plum"]),
    "onion_dry":   (["प्याज", "onion"], ["हरियो", "green"]),
    "cauliflower": (["काउली", "cauliflower"], []),
    "cabbage":     (["बन्दा", "cabbage"], []),
    "carrot":      (["गाजर", "carrot"], []),
    "radish":      (["मूला", "मुला", "radish"], []),
    "eggplant":    (["भण्टा", "भन्टा", "brinjal", "eggplant"], []),
    "beans":       (["सिमी", "बोडी", "bean"], []),
    "peas":        (["मटर", "केराउ", "peas"], []),
    "bitter_gourd": (["तितो", "करेला", "bitter"], []),
    "okra":        (["भिण्डी", "भिन्डी", "रामतोरिया", "okra"], []),
    "pumpkin":     (["फर्सी", "pumpkin"], ["मुन्टा", "munta"]),
}
CROPS = {g: ([norm(k) for k in inc], [norm(k) for k in exc]) for g, (inc, exc) in _CROPS.items()}


def classify(name):
    n = norm(name)
    for g, (inc, exc) in CROPS.items():
        if any(k in n for k in inc) and not any(k in n for k in exc):
            return g
    return None


_ORIGIN = {"indian": ["भारतीय", "indian"], "nepali": ["नेपाली", "nepali"],
           "local": ["लोकल", "स्थानीय", "local"], "terai": ["तराई", "terai"],
           "tunnel": ["टनेल", "tunnel"]}
_SIZE = {"large": ["ठूलो", "large"], "small": ["सानो", "small"]}


def _tag(name, table):
    n = norm(name)
    for tag, words in table.items():
        if any(norm(w) in n for w in words):
            return tag
    return None


# ----------------------------- UNIT HELPERS (owner's code) -------------------
def _u(x):
    return norm(x).replace(" ", "").replace(".", "")


_KG = {_u(x) for x in ["केजी", "के.जी.", "किग्रा", "कि.ग्रा.", "किलो", "kg", "kgs", "kilogram"]}
_QTL = {_u(x) for x in ["क्विन्टल", "क्विण्टल", "quintal"]}
_TON = {_u(x) for x in ["टन", "मेट्रिकटन", "ton", "tonne"]}


def kg_factor(unit):
    u = _u(unit)
    if u in _KG:
        return 1.0
    if u in _QTL:
        return 100.0
    if u in _TON:
        return 1000.0
    return float("nan")


def unit_type(unit):
    if kg_factor(unit) == kg_factor(unit):
        return "weight"
    u = _u(unit)
    for t, words in {"dozen": ["दर्जन", "dozen"], "piece": ["गोटा", "piece", "pcs"],
                     "bundle": ["आटि", "आँटि", "bundle", "जुडा", "पुल्पा"]}.items():
        if any(_u(w) in u for w in words):
            return t
    return "other"


# ----------------------------- HTTP / PARSING (owner's code) -----------------
def make_session():
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "ne,en;q=0.8",
    })
    retry = Retry(total=1, backoff_factor=0.5, status_forcelist=(500, 502, 503, 504))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def _find_records(obj):
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return obj
    if isinstance(obj, dict):
        for v in obj.values():
            r = _find_records(v)
            if r:
                return r
    return None


def response_to_df(resp):
    """Turn a response (HTML table or JSON) into the biggest DataFrame, or None."""
    text = resp.text
    if "json" in resp.headers.get("content-type", "") or text.lstrip().startswith(("{", "[")):
        try:
            recs = _find_records(resp.json())
            if recs:
                return pd.DataFrame(recs)
        except Exception:
            pass
    try:
        tables = pd.read_html(io.StringIO(text))
    except (ValueError, ImportError):
        return None
    tables = [t for t in tables if t.shape[1] >= 3 and len(t) >= 3]
    if not tables:
        return None
    df = max(tables, key=len).copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [" ".join(map(str, c)).strip() for c in df.columns]
    df.columns = [str(c).strip() for c in df.columns]
    return df


def split_cols(df):
    num = [c for c in df.columns if to_num(df[c]).notna().mean() > 0.7]
    txt = [c for c in df.columns if c not in num]
    return num, txt


def standardize_prices(df, d):
    num, txt = split_cols(df)
    if len(num) < 3 or not txt:
        return None
    mn, mx, av = num[-3:]
    out = pd.DataFrame({
        "date": d.isoformat(),
        "commodity_raw": df[txt[0]].astype(str).str.strip(),
        "unit_raw": df[txt[1]].astype(str).str.strip() if len(txt) > 1 else "",
        "min_price": to_num(df[mn]), "max_price": to_num(df[mx]), "avg_price": to_num(df[av]),
    })
    out = out[out["avg_price"].notna() & (out["commodity_raw"] != "nan")].reset_index(drop=True)
    if out.empty:
        return None
    key = "|".join(f"{n}:{a}" for n, a in zip(out.commodity_raw, out.avg_price))
    out["day_hash"] = hashlib.md5(key.encode()).hexdigest()[:10]
    return out


def standardize_arrivals(df, d):
    num, txt = split_cols(df)
    if not num or not txt:
        return None
    q = num[-1]
    used = {txt[0], q} | ({txt[1]} if len(txt) > 1 else set())
    others = [c for c in df.columns if c not in used]
    out = pd.DataFrame({
        "date": d.isoformat(),
        "commodity_raw": df[txt[0]].astype(str).str.strip(),
        "arrival_unit": df[txt[1]].astype(str).str.strip() if len(txt) > 1 else "",
        "arrival_qty": to_num(df[q]),
        "other_cols": (df[others].astype(str).apply(
            lambda r: json.dumps(r.to_dict(), ensure_ascii=False), axis=1) if others else ""),
    })
    out = out[out["arrival_qty"].notna() & (out["commodity_raw"] != "nan")].reset_index(drop=True)
    return None if out.empty else out


STANDARDIZE = {"prices": standardize_prices, "arrivals": standardize_arrivals}


class Fetcher:
    """Owner's fetcher: auto-detects how the site takes a date. The detected form is cached in the DB."""

    def __init__(self, label, url):
        self.label, self.url = label, url
        self.s = make_session()
        self.strategy = (db.get_meta("fetch_strategy", {}) or {}).get(label)

    def _request(self, c, d):
        params = {**c["extra"], c["field"]: d.isoformat()}
        hdr = {"Referer": self.url}
        if c["method"] == "get":
            return self.s.get(c["action"], params=params, headers=hdr, timeout=TIMEOUT)
        return self.s.post(c["action"], data=params, headers=hdr, timeout=TIMEOUT)

    def _candidates(self):
        from bs4 import BeautifulSoup
        r = self.s.get(self.url, timeout=TIMEOUT)
        soup = BeautifulSoup(r.text, "html.parser")
        meta = soup.find("meta", {"name": "csrf-token"})
        token = {"_token": meta["content"]} if meta and meta.get("content") else {}
        cands, date_inputs = [], soup.find_all("input", {"type": "date"})
        for form in soup.find_all("form"):
            di = form.find("input", {"type": "date"})
            if di is None:
                continue
            hidden = {i["name"]: i.get("value", "") for i in form.find_all("input", {"type": "hidden"})
                      if i.get("name")}
            cands.append({"method": (form.get("method") or "get").lower(),
                          "action": urljoin(self.url, form.get("action") or self.url),
                          "field": di.get("name") or di.get("id") or "date",
                          "extra": hidden, "why": "form"})
        names = [x for di in date_inputs for x in (di.get("name"), di.get("id")) if x]
        names += ["date", "datePricing", "date_pricing", "pricing_date", "search_date", "selectedDate"]
        for n in dict.fromkeys(names):
            cands.append({"method": "get", "action": self.url, "field": n, "extra": {}, "why": "guess"})
            cands.append({"method": "post", "action": self.url, "field": n, "extra": dict(token), "why": "guess"})
        return cands

    def discover(self):
        end = kathmandu_today()
        tests = [end - dt.timedelta(days=n) for n in (1, 45, 90)]
        for c in self._candidates():
            try:
                valid = []
                for d in tests:
                    r = self._request(c, d)
                    if r.status_code != 200:
                        raise ValueError(r.status_code)
                    df = response_to_df(r)
                    if df is not None and len(df) >= 5:
                        valid.append(df)
                if len(valid) >= 2 and len({x.to_csv() for x in valid}) > 1:
                    self.strategy = c
                    saved = db.get_meta("fetch_strategy", {}) or {}
                    saved[self.label] = c
                    db.set_meta("fetch_strategy", saved)
                    log.info("[%s] detected: %s %s field=%s", self.label, c["method"].upper(), c["action"], c["field"])
                    return True
            except Exception:
                continue
        return False

    def fetch(self, d, tries=TRIES):
        if self.strategy is None and not self.discover():
            raise RuntimeError(f"could not find how the {self.label} page takes a date")
        last = None
        for i in range(tries):
            try:
                r = self._request(self.strategy, d)
                if r.status_code in (419, 403):
                    self.discover()
                    continue
                r.raise_for_status()
                return response_to_df(r)
            except Exception as e:
                last = e
                time.sleep(1 * (i + 1))
        raise RuntimeError(f"{d}: {last}")


def enrich(df, kind):
    df = df.copy()
    df["name_norm"] = df["commodity_raw"].map(norm)
    df["crop_group"] = df["commodity_raw"].map(classify)
    df["origin"] = df["commodity_raw"].map(lambda x: _tag(x, _ORIGIN))
    df["size"] = df["commodity_raw"].map(lambda x: _tag(x, _SIZE))
    if kind == "prices":
        f = df["unit_raw"].map(kg_factor)
        df["unit_type"] = df["unit_raw"].map(unit_type)
        for c in ("min", "max", "avg"):
            df[f"{c}_price_kg"] = df[f"{c}_price"] / f
    else:
        df["arrival_kg"] = df["arrival_qty"] * df["arrival_unit"].map(kg_factor)
        df["unit_type"] = df["arrival_unit"].map(unit_type)
    return df


# ----------------------------- APP SIDE --------------------------------------
_lock = threading.Lock()


def kathmandu_today() -> dt.date:
    """Calendar date in Asia/Kathmandu."""
    return now().date()


def default_fetchers() -> dict[str, Any]:
    return {label: Fetcher(label, url) for label, url in PAGES.items()}


def missing_days(latest: str | None, today: dt.date) -> list[dt.date]:
    """Days after the latest stored date up to today (at most MAX_BACK_DAYS back)."""
    start = today - dt.timedelta(days=MAX_BACK_DAYS)
    if latest:
        start = max(start, dt.date.fromisoformat(latest) + dt.timedelta(days=1))
    return [start + dt.timedelta(days=n) for n in range((today - start).days + 1)]


def run(progress: Callable[[float, str], None] | None = None, fetchers: dict | None = None,
        budget_s: float = BUDGET_S, chunk: int = CHUNK_DAYS) -> dict:
    """Fetch missing days, store new rows, refresh forecasts. Never raises; returns a plain result."""
    progress = progress or (lambda p, m: None)
    if not _lock.acquire(blocking=False):
        return {"ok": False, "rows_added": 0, "error": "A fetch is already running."}
    t0 = time.time()
    result: dict = {"ok": True, "rows_added": 0, "days_added": [], "empty_days": [], "errors": []}
    try:
        latest = (db.q1("SELECT MAX(date) AS d FROM prices") or {}).get("d")
        result["latest_before"] = latest
        days = missing_days(latest, kathmandu_today())
        known_empty = set(db.get_meta("fetch_empty_days", []) or [])
        days = [d for d in days if d.isoformat() not in known_empty or d >= kathmandu_today() - dt.timedelta(days=1)]
        todo = days[:chunk]
        result["days_left"] = max(0, len(days) - len(todo))
        if not todo:
            progress(1.0, "Already up to date.")
            result["latest_date"] = latest
            return result
        fetchers = fetchers or default_fetchers()
        for i, d in enumerate(todo):
            if time.time() - t0 > budget_s:
                result["days_left"] += len(todo) - i
                progress(i / len(todo), "Time limit reached; the rest will be fetched on the next run.")
                break
            progress(i / len(todo), f"Fetching {d.isoformat()}")
            try:
                raw_p = fetchers["prices"].fetch(d)
                std_p = standardize_prices(raw_p, d) if raw_p is not None else None
                std_a = None
                if std_p is not None and "arrivals" in fetchers:
                    try:
                        raw_a = fetchers["arrivals"].fetch(d)
                        std_a = standardize_arrivals(raw_a, d) if raw_a is not None else None
                    except Exception as e:  # arrivals are optional; prices still count
                        result["errors"].append(f"{d}: arrivals could not be read ({e})")
            except Exception as e:
                result["errors"].append(f"{d}: {e}")
                continue
            if std_p is None:
                known_empty.add(d.isoformat())
                result["empty_days"].append(d.isoformat())
                continue
            n = store_day(d, std_p, std_a)
            if n:
                result["rows_added"] += n
                result["days_added"].append(d.isoformat())
        db.set_meta("fetch_empty_days", sorted(known_empty)[-200:])
        if result["rows_added"]:
            progress(0.9, f"Added {result['rows_added']} rows. Updating today's estimates")
            after_new_data()
        latest_after = (db.q1("SELECT MAX(date) AS d FROM prices") or {}).get("d")
        result["latest_date"] = latest_after
        if result["errors"] and not result["rows_added"]:
            result["ok"] = False
            result["error"] = "Could not reach the Kalimati website or read its table. Old data is kept. " \
                              + result["errors"][0]
        progress(1.0, f"Done. Rows added: {result['rows_added']}. Latest date: {latest_after}")
    except Exception as e:  # never crash the app; keep the old data
        log.exception("fetch failed")
        result.update(ok=False, error=f"Fetch failed, old data kept: {type(e).__name__}: {e}")
    finally:
        _lock.release()
        result["seconds"] = round(time.time() - t0, 2)
        db.set_meta("fetch_last", {"at": now_iso(), **{k: result.get(k) for k in
                                                       ("ok", "rows_added", "latest_date", "error", "days_left")}})
        if not result.get("ok"):
            db.x("INSERT INTO webhook_log(ts,kind,ok,note,payload) VALUES(?,?,?,?,?)",
                 (now_iso(), "fetch", 0, (result.get("error") or "")[:300], json.dumps(result.get("errors", [])[:5])))
    return result


def store_day(d: dt.date, std_p: pd.DataFrame, std_a: pd.DataFrame | None) -> int:
    """Validate one fetched day like the ZIP ingestion and append it. Idempotent (date + crop + variant)."""
    day = d.isoformat()
    P = enrich(std_p, "prices")
    P = P[P["crop_group"].notna()].copy()
    for c in ("min_price_kg", "max_price_kg", "avg_price_kg"):
        P[c] = pd.to_numeric(P[c], errors="coerce")
    P = P[P["avg_price_kg"].notna() & (P["avg_price_kg"] > 0) & (P["avg_price_kg"] < 5000)]
    if P.empty:
        return 0
    carried = _carried_over(day, str(std_p["day_hash"].iloc[0]), P)
    known = {(r["crop"], r["variant"]): r["is_primary"] for r in
             db.q("SELECT crop, variant, MAX(is_primary) AS is_primary FROM prices GROUP BY crop, variant")}
    P = P.drop_duplicates(subset=["crop_group", "commodity_raw"], keep="last")
    rows = [(day, r.crop_group, str(r.commodity_raw), r.origin or "", r.size or "",
             _f(r.min_price_kg), _f(r.max_price_kg), float(r.avg_price_kg), int(carried),
             int(known[(r.crop_group, str(r.commodity_raw))]))
            for r in P.itertuples(index=False) if (r.crop_group, str(r.commodity_raw)) in known]
    daily = (P.groupby("crop_group").agg(avg=("avg_price_kg", "mean"), mn=("min_price_kg", "min"),
                                         mx=("max_price_kg", "max"), n=("commodity_raw", "nunique")))
    arr = {}
    if std_a is not None:
        A = enrich(std_a, "arrivals")
        A = A[A["crop_group"].notna() & A["arrival_kg"].notna()]
        arr = A.groupby("crop_group")["arrival_kg"].sum().to_dict()
    drows = [(day, crop, _f(g.avg), _f(g.mn), _f(g.mx), _f(g.n), int(carried), _f(arr.get(crop)))
             for crop, g in daily.iterrows()]
    with db.connect() as c:
        before = c.total_changes
        c.executemany("INSERT OR IGNORE INTO prices VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
        c.executemany("INSERT OR IGNORE INTO daily_crop VALUES(?,?,?,?,?,?,?,?)", drows)
        added = c.total_changes - before
    hashes = db.get_meta("fetch_day_hash", {}) or {}
    hashes[day] = str(std_p["day_hash"].iloc[0])
    db.set_meta("fetch_day_hash", dict(sorted(hashes.items())[-60:]))
    return int(added)


def _carried_over(day: str, day_hash: str, P: pd.DataFrame) -> bool:
    """Same table as the previous market day = carried over (owner's day_hash rule)."""
    hashes = db.get_meta("fetch_day_hash", {}) or {}
    prev = max((k for k in hashes if k < day), default=None)
    if prev is not None:
        return hashes[prev] == day_hash
    last = db.q1("SELECT MAX(date) AS d FROM prices WHERE date < ?", (day,))
    if not last or not last["d"]:
        return False
    old = {(r["crop"], r["variant"]): r["avg_kg"] for r in
           db.q("SELECT crop, variant, avg_kg FROM prices WHERE date=?", (last["d"],))}
    new = {(r.crop_group, str(r.commodity_raw)): float(r.avg_price_kg) for r in P.itertuples(index=False)}
    common = [k for k in new if k in old]
    return bool(common) and all(abs(new[k] - old[k]) < 1e-9 for k in common)


def _f(v) -> float | None:
    try:
        return None if v is None or pd.isna(v) else float(v)
    except (TypeError, ValueError):
        return None


def after_new_data() -> None:
    """Carry the dataset version forward, refresh caches, forecasts, ledger and weather outlook."""
    from app.core import data
    latest = (db.q1("SELECT MAX(date) AS d FROM prices") or {}).get("d")
    ds = db.q1("SELECT id, report_json FROM dataset_versions WHERE active=1")
    if ds:
        rep = json.loads(ds["report_json"] or "{}")
        if rep.get("date_range"):
            rep["date_range"] = [rep["date_range"][0], latest]
        rep["fetched_through"] = latest
        db.x("UPDATE dataset_versions SET report_json=? WHERE id=?", (json.dumps(rep), ds["id"]))
    try:
        refresh_forecasts()
    except Exception:
        log.exception("forecast refresh after fetch failed; previous estimates kept")
    try:
        from app.forecast.registry import fill_ledger
        fill_ledger()
    except Exception:
        log.exception("ledger fill failed")
    try:
        from app.training import _save_outlooks
        _save_outlooks()
    except Exception:
        log.exception("weather outlook refresh failed")
    data.invalidate()


def refresh_forecasts() -> int:
    """Recompute today's forecast for every crop x horizon from the new origin day with the saved models."""
    import joblib

    from app.config import MODELS_DIR
    from app.forecast.baselines import seasonal_naive, seasonal_range
    from app.forecast.features import build_features, build_target
    from app.forecast.predict import latest_run_id
    from app.forecast.prep import HORIZON_DAYS, build_frame, load_tables
    from app.forecast.registry import _ledger, season_band

    rid = latest_run_id()
    if rid is None:
        return 0
    prices, daily, weather = load_tables()
    n = 0
    for crop in sorted(prices["crop"].unique().tolist()):
        frame = build_frame(prices, daily, weather, crop)
        if frame.empty:
            continue
        X = build_features(frame)
        origin = frame.index.max()
        price0 = float(frame["price"].ffill().iloc[-1])
        for row in db.q("SELECT * FROM forecasts WHERE run_id=? AND crop=?", (rid, crop)):
            h = row["horizon"]
            if row["status"] == "unavailable" or row["p50"] is None:
                continue
            y = build_target(frame, h)
            valid = y.notna() & X["lp"].notna()
            p10 = p25 = p50 = p75 = p90 = None
            model_name = row["model_name"]
            if row["status"] == "pattern only":
                rng = seasonal_range(y[valid].values, X.index[valid], origin, (0.1, 0.25, 0.5, 0.75, 0.9))
                if rng:
                    p10, p25, p50, p75, p90 = (price0 * np.exp(v) for v in rng)
            else:
                path = MODELS_DIR / "price" / f"{crop}_{h}.joblib"
                mid = None
                art = None
                try:
                    art = joblib.load(path)
                    mid = _point(art, X, y, valid, seasonal_naive)
                except Exception as e:  # scikit-learn missing on this host, or file missing
                    log.info("model %s %s not loadable here (%s); moving the last estimate to today's price", crop, h, e)
                if mid is None or art is None:
                    ratio = {k: (row[k] / row["price0"]) if row[k] and row["price0"] else None
                             for k in ("p10", "p25", "p50", "p75", "p90")}
                    p10, p25, p50, p75, p90 = (price0 * ratio[k] if ratio[k] else None
                                               for k in ("p10", "p25", "p50", "p75", "p90"))
                else:
                    off, off50 = art.get("offsets"), art.get("offsets50")
                    p50 = price0 * np.exp(mid)
                    if off:
                        p10, p90 = price0 * np.exp(mid + off[0]), price0 * np.exp(mid + off[1])
                    if off50:
                        p25, p75 = price0 * np.exp(mid + off50[0]), price0 * np.exp(mid + off50[1])
            if p50 is None:
                continue
            band_lo, band_hi = season_band(frame, origin + pd.Timedelta(days=HORIZON_DAYS[h]))
            pct = (p50 / price0 - 1) * 100 if price0 else None
            db.x("UPDATE forecasts SET origin_date=?, p10=?, p25=?, p50=?, p75=?, p90=?, price0=?, pct_change_p50=?, "
                 "band_lo=?, band_hi=?, model_name=? WHERE run_id=? AND crop=? AND horizon=?",
                 (origin.strftime("%Y-%m-%d"), p10, p25, p50, p75, p90, price0, pct, band_lo, band_hi, model_name,
                  rid, crop, h))
            _ledger(origin, crop, h, p10, p50, p90, price0, row["status"])
            n += 1
    return n


def _point(art: dict, X: pd.DataFrame, y: pd.Series, valid: pd.Series, seasonal_naive) -> float | None:
    """Point estimate (log ratio) for the last row with a saved model. Mirrors registry._final_fit."""
    obj, row = art["model"], X.iloc[[-1]]
    xv = row[art.get("features", list(X.columns))].values

    def base(name: str) -> float:
        if name == "persistence":
            return 0.0
        if name == "seasonal_naive":
            return float(seasonal_naive(y[valid].values, X.index[valid], row.index)[0])
        if name == "mean_reversion":
            b = obj.get("b", 0.0) if isinstance(obj, dict) else 0.0
            return float(np.nan_to_num(b * row["mr_gap"].values[0]))
        return 0.0

    if isinstance(obj, dict):
        if obj.get("type") == "blend":
            b = base(obj["base"])
            return b + (art.get("lambda") or 0.0) * (float(obj["hgb"].predict(xv)[0]) - b)
        return base(obj.get("type", "persistence"))
    return float(obj.predict(xv)[0])


# ----------------------------- DAY-CHANGE TRIGGER -----------------------------
def claim_today() -> bool:
    """True for exactly one caller per Asia/Kathmandu day (atomic in SQLite, works across instances)."""
    today = kathmandu_today().isoformat()
    with db.connect() as c:
        c.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('fetch_day', '\"\"')")
        cur = c.execute("UPDATE meta SET value=? WHERE key='fetch_day' AND value<>?",
                        (json.dumps(today), json.dumps(today)))
        return cur.rowcount == 1
