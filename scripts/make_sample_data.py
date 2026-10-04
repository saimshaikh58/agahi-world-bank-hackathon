"""Generate a small SYNTHETIC dataset (clearly labelled) with the same columns and location keys as the real
bundle. Seeded, so the output is identical every run. Usage: python scripts/make_sample_data.py [out_dir]"""
from __future__ import annotations

import sys
from pathlib import Path

import _bootstrap  # noqa: F401
import numpy as np
import pandas as pd

SEED = 2024
CROPS = {  # crop: (variant name, origin, size, base price Rs/kg, seasonal amplitude)
    "tomato": ("गोलभेडा सानो(लोकल)", "local", "small", 60, 0.45),
    "potato": ("आलु रातो(लाम्चो)", "", "", 45, 0.20),
    "onion_dry": ("प्याज सुकेको (भारतीय)", "indian", "", 70, 0.25),
    "cauliflower": ("काउली स्थानिय", "local", "", 70, 0.50),
    "cabbage": ("बन्दा(लोकल)", "local", "", 40, 0.40),
}
LOCATIONS = ["kathmandu_valley", "kavre_dhulikhel", "nuwakot_bidur", "dhading_besi", "sindhupalchok",
             "makwanpur_hetauda", "boundary_mean"]


def weather(rng: np.random.Generator) -> pd.DataFrame:
    """2015-01-01 .. 2026-09-30 daily weather with a monsoon cycle."""
    dates = pd.date_range("2015-01-01", "2026-09-30", freq="D")
    doy = dates.dayofyear.values
    monsoon = np.clip(np.sin((doy - 140) / 120 * np.pi), 0, None)
    frames = []
    base = None
    for i, loc in enumerate(LOCATIONS[:-1]):
        wet = rng.random(len(dates)) < (0.08 + 0.75 * monsoon)
        rain = np.where(wet, rng.gamma(1.2, 6 + 14 * monsoon), 0.0)
        tmax = 22 + 7 * np.sin((doy - 80) / 365 * 2 * np.pi) - i * 0.6 + rng.normal(0, 1.5, len(dates))
        tmin = tmax - 9 - 3 * (1 - monsoon) + rng.normal(0, 1, len(dates))
        wind = np.abs(rng.normal(1.5, 0.6, len(dates)))
        df = pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "location": loc, "tmin_c": tmin.round(2),
                           "tmax_c": tmax.round(2), "rain_mm": rain.round(2), "wind_ms": wind.round(2),
                           "heat_index_c": tmax.round(2)})
        frames.append(df)
        base = df[["tmin_c", "tmax_c", "rain_mm", "wind_ms", "heat_index_c"]] if base is None else base + df[
            ["tmin_c", "tmax_c", "rain_mm", "wind_ms", "heat_index_c"]]
    avg = (base / (len(LOCATIONS) - 1)).round(3)
    avg.insert(0, "location", "boundary_mean")
    avg.insert(0, "date", dates.strftime("%Y-%m-%d"))
    frames.append(avg)
    return pd.concat(frames, ignore_index=True)


def prices(rng: np.random.Generator, wx: pd.DataFrame, years: int = 3) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Anchor series and daily-by-crop with seasonality, a rain-to-arrivals effect and noise."""
    end = pd.Timestamp("2026-09-30")
    dates = pd.date_range(end - pd.Timedelta(days=365 * years), end, freq="D")
    area = wx[wx["location"] == "boundary_mean"].set_index("date")["rain_mm"]
    rain7 = pd.Series(area.reindex(dates.strftime("%Y-%m-%d")).values, index=dates).rolling(7, min_periods=1).sum()
    anchor, daily = [], []
    for crop, (variant, origin, size, base, amp) in CROPS.items():
        doy = dates.dayofyear.values
        season = amp * np.sin((doy - rng.integers(0, 365)) / 365 * 2 * np.pi)
        arrivals = 40000 * (1 - 0.004 * rain7.values) * np.exp(rng.normal(0, 0.15, len(dates)))
        ar = np.zeros(len(dates))
        for t in range(1, len(dates)):
            ar[t] = 0.9 * ar[t - 1] + rng.normal(0, 0.04)
        logp = np.log(base) + season + ar - 0.3 * np.log(arrivals / 40000)
        p = np.exp(logp)
        carried = rng.random(len(dates)) < 0.03
        for d, v, c, a in zip(dates, p, carried, arrivals):
            ds = d.strftime("%Y-%m-%d")
            anchor.append((ds, crop, variant, origin, size, round(v * 0.9, 1), round(v * 1.1, 1), round(v, 1), bool(c)))
            daily.append((ds, crop, round(v, 2), round(v * 0.85, 1), round(v * 1.15, 1), 1.0, bool(c), round(a)))
    a = pd.DataFrame(anchor, columns=["date", "crop_group", "commodity_raw", "origin", "size", "min_price_kg",
                                      "max_price_kg", "avg_price_kg", "carried_over"])
    d = pd.DataFrame(daily, columns=["date", "crop_group", "avg_price_kg", "min_price_kg", "max_price_kg",
                                     "n_variants", "carried_over", "arrivals_kg"])
    return a, d


def generate(out: Path, years: int = 3) -> list[Path]:
    """Write SAMPLE_*.csv files into out."""
    rng = np.random.default_rng(SEED)
    out.mkdir(parents=True, exist_ok=True)
    wx = weather(rng)
    a, d = prices(rng, wx, years)
    paths = [out / "SAMPLE_anchor_series.csv", out / "SAMPLE_daily_by_crop.csv", out / "SAMPLE_weather_daily.csv"]
    a.to_csv(paths[0], index=False)
    d.to_csv(paths[1], index=False)
    wx.to_csv(paths[2], index=False)
    (out / "README_SAMPLE.txt").write_text("SYNTHETIC SAMPLE DATA. Not real Kalimati prices or real weather.\n", encoding="utf-8")
    return paths


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else _bootstrap.ROOT / "sample_data"
    for p in generate(target):
        print("wrote", p)
