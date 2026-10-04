"""Farmer locations, built from the weather file at ingestion time (never hard-coded lists)."""
from __future__ import annotations

from app import db

AREA_KEY = "boundary_mean"

# Display names and coordinates for keys we know. Nepali names need native review.
KNOWN = {
    "kathmandu_valley": ("Kathmandu Valley", "Kathmandu upatyaka", "काठमाडौं उपत्यका", 27.70, 85.32),
    "kavre_dhulikhel": ("Kavre (Dhulikhel)", "Kavre (Dhulikhel)", "काभ्रे (धुलिखेल)", 27.62, 85.55),
    "nuwakot_bidur": ("Nuwakot (Bidur)", "Nuwakot (Bidur)", "नुवाकोट (बिदुर)", 27.91, 85.17),
    "dhading_besi": ("Dhading (Dhading Besi)", "Dhading (Dhading Besi)", "धादिङ (धादिङबेंसी)", 27.87, 84.90),
    "sindhupalchok": ("Sindhupalchok (Chautara)", "Sindhupalchok (Chautara)", "सिन्धुपाल्चोक (चौतारा)", 27.78, 85.71),
    "makwanpur_hetauda": ("Makwanpur (Hetauda)", "Makwanpur (Hetauda)", "मकवानपुर (हेटौंडा)", 27.43, 85.03),
}
ORDER = list(KNOWN.keys())
AREA_NAMES = ("Whole area", "Sabai kshetra", "सबै क्षेत्र")


def humanise(key: str) -> str:
    """kathmandu_valley -> Kathmandu Valley."""
    return " ".join(p.capitalize() for p in key.replace("-", "_").split("_") if p)


def build_locations(keys: list[str]) -> list[dict]:
    """Build location rows from the weather file's location keys."""
    rows: list[dict] = []
    extra = sorted(k for k in keys if k not in KNOWN and k != AREA_KEY)
    known = [k for k in ORDER if k in keys]
    for i, key in enumerate(known + extra):
        if key in KNOWN:
            en, rn, ne, lat, lon = KNOWN[key]
        else:
            en = rn = ne = humanise(key)
            lat = lon = None
        rows.append(dict(key=key, name_en=en, name_rn=rn, name_ne=ne, lat=lat, lon=lon, sort_order=i + 1, selectable=1))
    en, rn, ne = AREA_NAMES
    rows.append(dict(key=AREA_KEY, name_en=en, name_rn=rn, name_ne=ne, lat=27.70, lon=85.30,
                     sort_order=999, selectable=0))
    return rows


def save_locations(rows: list[dict]) -> None:
    """Replace the locations table."""
    with db.connect() as c:
        c.execute("DELETE FROM locations")
        c.executemany(
            "INSERT INTO locations(key,name_en,name_rn,name_ne,lat,lon,sort_order,selectable) VALUES(?,?,?,?,?,?,?,?)",
            [(r["key"], r["name_en"], r["name_rn"], r["name_ne"], r["lat"], r["lon"], r["sort_order"], r["selectable"])
             for r in rows])


def all_locations() -> list[dict]:
    """All locations including the area average, in sort order."""
    return db.q("SELECT * FROM locations ORDER BY sort_order")


def selectable() -> list[dict]:
    """Locations a farmer can pick (excludes boundary_mean)."""
    return db.q("SELECT * FROM locations WHERE selectable=1 ORDER BY sort_order")


def get(key: str | None) -> dict | None:
    """One location row."""
    if not key:
        return None
    return db.q1("SELECT * FROM locations WHERE key=?", (key,))


def short_name(loc: dict | None, lang: str) -> str:
    """Short district name (first word) for SMS, in the reply language."""
    if not loc:
        return ""
    if loc["key"] == AREA_KEY:
        return {"en": "Whole area", "rn": "Sabai thau", "ne": "सबै क्षेत्र"}[lang]
    name = loc.get(f"name_{lang}") or loc["name_en"]
    return name.split(" ")[0]
