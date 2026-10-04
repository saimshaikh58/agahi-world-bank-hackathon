"""Brand colours: read from app/static/brand/logo.png at startup (Pillow), env overrides, calm fallback."""
from __future__ import annotations

import colorsys
import logging
import re

from app.config import STATIC_DIR, settings

log = logging.getLogger("agahi.brand")
LOGO = STATIC_DIR / "brand" / "logo.png"
# Read from the supplied artwork: deep forest green field (#1f3b29) with a cream wordmark (#e8e3c9).
# The shipped logo.png is the wordmark on a transparent background, so the green is kept here.
LOGO_PRIMARY = "#1f3b29"
LOGO_ACCENT = "#e8e3c9"
FALLBACK_PRIMARY = "#1f5f4a"
FALLBACK_ACCENT = "#d9c27a"
HEX = re.compile(r"^#?[0-9a-fA-F]{6}$")


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c))) for c in rgb)


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _mix(a: str, b: str, t: float) -> str:
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(ra[i] + (rb[i] - ra[i]) * t for i in range(3)))


def extract(path=LOGO) -> tuple[str | None, str] | None:
    """Colours of the logo, ignoring transparent pixels and greys. Returns (primary or None, accent).
    A logo that is only a light wordmark (transparent background) gives its colour as the accent and no primary."""
    try:
        from PIL import Image
        im = Image.open(path).convert("RGBA")
        im.thumbnail((512, 512))
        opaque = Image.new("RGB", im.size, (255, 255, 255))
        mask = im.getchannel("A").point(lambda a: 255 if a >= 200 else 0)
        if not mask.getbbox():
            return None
        opaque.paste(im.convert("RGB"), mask=mask)
        q = opaque.quantize(colors=6)
        pal = q.getpalette()
        counts = sorted(q.getcolors(), reverse=True)
    except Exception as e:  # no logo or unreadable -> fallback
        log.info("Logo colours not read (%s); using defaults", e)
        return None
    cands = []
    for _, idx in counts:
        r, g, b = pal[idx * 3:idx * 3 + 3]
        if (r, g, b) == (255, 255, 255):
            continue  # the transparent area
        _, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        if s < 0.12 and 0.12 < l < 0.9:
            continue  # grey
        cands.append((_hex((r, g, b)), l))
    if not cands:
        return None
    first, fl = cands[0]
    if fl > 0.6:  # only a light wordmark: that is the accent; the primary comes from the artwork's field
        return None, first
    others = [c for c in cands[1:] if abs(c[1] - fl) > 0.3]
    accent = max(others, key=lambda c: abs(c[1] - fl))[0] if others else FALLBACK_ACCENT
    return first, accent


def palette() -> dict:
    """CSS variables for templates."""
    primary, accent = LOGO_PRIMARY, LOGO_ACCENT
    found = extract() if LOGO.exists() else None
    if found:
        primary, accent = (found[0] or LOGO_PRIMARY), found[1]
    elif not LOGO.exists():
        primary, accent = FALLBACK_PRIMARY, FALLBACK_ACCENT
    if HEX.match(settings.brand_primary):
        primary = "#" + settings.brand_primary.lstrip("#")
    if HEX.match(settings.brand_accent):
        accent = "#" + settings.brand_accent.lstrip("#")
    return {"brand_700": _mix(primary, "#000000", 0.2), "brand_600": primary, "brand_500": _mix(primary, "#ffffff", 0.18),
            "brand_100": _mix(primary, "#ffffff", 0.85), "brand_50": _mix(primary, "#ffffff", 0.93),
            "accent": accent, "has_logo": LOGO.exists()}
