import numpy as np
import pandas as pd

from app import brand, db, http
from app.config import settings
from app.core import advisor, data, replies
from app.core.engine import handle_message
from app.forecast import registry
from app.weather import live, outlook


def test_no_internet_falls_back_to_climatology(monkeypatch):
    monkeypatch.setattr(settings, "live_weather", True)
    live.reset_backoff()
    db.x("DELETE FROM weather_cache")

    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(http, "get_json", boom)
    w = outlook.next7("kathmandu_valley")
    assert w["method"] == "climatology"
    r = replies.weather7("en", "kathmandu_valley", False, False)
    assert "From past years, not a forecast" in r.text


def test_timeout_is_five_seconds():
    assert http.TIMEOUT_S == 5.0


def test_not_trained_message(fresh_phone):
    handle_message("web", fresh_phone, "1", offline=True)
    handle_message("web", fresh_phone, "1", offline=True)
    r = handle_message("web", fresh_phone, "tomato 14 din", offline=True)
    assert "tayar chhaina" in r.text or "not trained" in r.text


def test_no_logo_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(brand, "LOGO", tmp_path / "missing.png")
    p = brand.palette()
    assert p["brand_600"] == brand.FALLBACK_PRIMARY and not p["has_logo"]


def test_short_series_unavailable():
    rid = db.x("INSERT INTO model_runs(started_at,mode) VALUES('x','fast')")
    idx = pd.date_range("2025-01-01", periods=200, freq="D")
    f = pd.DataFrame({"price": np.linspace(40, 60, 200), "price2": np.nan, "arrivals": np.nan, "rain": 1.0, "tmax": 25.0}, index=idx)
    from app.forecast.features import build_features
    res = registry._train_cell(rid, "peas", "d7", f, build_features(f), "fast")
    assert res["summary"]["status"] == "unavailable"
    db.x("DELETE FROM forecasts WHERE run_id=?", (rid,))
    db.x("DELETE FROM model_runs WHERE id=?", (rid,))


def test_offline_adds_as_of(fresh_phone):
    handle_message("web", fresh_phone, "1", offline=True)
    handle_message("web", fresh_phone, "1", offline=True)
    r = handle_message("web", fresh_phone, "LANG EN", offline=True)
    r = handle_message("web", fresh_phone, "tomato", offline=True)
    assert "(Data from" in r.text


def test_carried_over_latest_day_says_no_new_price():
    s = data.store()
    today = s.today
    row = db.q1("SELECT variant FROM prices WHERE crop='tomato' AND is_primary=1 AND date=?", (today,))
    db.x("UPDATE prices SET carried_over=1 WHERE crop='tomato' AND date=? AND variant=?", (today, row["variant"]))
    data.invalidate()
    try:
        r = replies.price("en", "tomato", "kathmandu_valley", True, False)
        assert "No new price" in r.text
    finally:
        db.x("UPDATE prices SET carried_over=0 WHERE crop='tomato' AND date=?", (today,))
        data.invalidate()


def test_advice_ignores_non_reliable_forecast(monkeypatch):
    s = data.store()
    monkeypatch.setattr(s, "forecast", lambda c, h: {"status": "indicative", "pct_change_p50": 30.0, "p10": 1, "p90": 2})
    a = advisor.advise("tomato", None, "kathmandu_valley", offline=True)
    assert a.no_forecast and a.used_forecast is None and a.confidence == "low"
    monkeypatch.setattr(s, "forecast", lambda c, h: {"status": "reliable", "pct_change_p50": 30.0, "p10": 1, "p90": 2})
    a = advisor.advise("tomato", None, "kathmandu_valley", offline=True)
    assert a.action == "HOLD" and a.confidence == "medium"
