"""SMS budgets: GSM-7 / UCS-2 detection, segment counting, fitting replies into at most 2 segments."""
from __future__ import annotations

from dataclasses import dataclass

GSM7_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
GSM7_EXT = set("^{}\\[]~|€\f")
GSM7_SINGLE, GSM7_MULTI = 160, 153
UCS2_SINGLE, UCS2_MULTI = 70, 67
MAX_SEGMENTS = 2
# Replace common non-GSM punctuation so English/Roman Nepali stay in cheap GSM-7.
SANITISE = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
            "…": "...", " ": " ", "•": "-", "·": "-", "°": ""}


def is_gsm7(text: str) -> bool:
    """True when every character is in the GSM-7 basic or extension table."""
    return all(ch in GSM7_BASIC or ch in GSM7_EXT for ch in text)


def sanitise(text: str) -> str:
    """Map typographic characters to GSM-7 equivalents (Devanagari untouched)."""
    return "".join(SANITISE.get(ch, ch) for ch in text)


def sms_stats(text: str) -> dict:
    """Return encoding (GSM7/UCS2), chars, units (septets or UTF-16 units) and segments."""
    if is_gsm7(text):
        units = sum(2 if ch in GSM7_EXT else 1 for ch in text)
        segs = 1 if units <= GSM7_SINGLE else -(-units // GSM7_MULTI)
        return {"encoding": "GSM7", "chars": len(text), "units": units, "segments": max(1, segs)}
    units = len(text.encode("utf-16-le")) // 2
    segs = 1 if units <= UCS2_SINGLE else -(-units // UCS2_MULTI)
    return {"encoding": "UCS2", "chars": len(text), "units": units, "segments": max(1, segs)}


def segments_of(text: str) -> int:
    """Shortcut: segment count."""
    return sms_stats(text)["segments"]


@dataclass
class Part:
    """One line (or block of lines) of a reply. Lower priority number = more important.
    Required parts are never dropped. alts are shorter versions tried before anything is dropped
    (for menus: one option per line, then two per line, then all on one line)."""
    text: str
    priority: int
    name: str = ""
    required: bool = False
    alts: tuple = ()


def _join(parts: list[Part]) -> str:
    return "\n".join(p.text.strip() for p in parts if p.text and p.text.strip())


def fit_parts(parts: list[Part], max_segments: int = MAX_SEGMENTS, transform=None) -> tuple[str, list[str]]:
    """Join parts one per line; shorten, then drop optional parts (least important first) until it fits.
    Returns (text, list of shortened or dropped part names)."""
    keep = [Part(p.text, p.priority, p.name, p.required, tuple(p.alts)) for p in parts if p.text]
    dropped: list[str] = []
    tf = transform or (lambda s: s)
    while segments_of(tf(_join(keep))) > max_segments:
        shrinkable = [p for p in keep if p.alts]
        if shrinkable:
            p = max(shrinkable, key=lambda x: x.priority)
            p.text, p.alts = p.alts[0], p.alts[1:]
            dropped.append(f"{p.name or 'part'} shortened")
            continue
        optional = [p for p in keep if not p.required]
        if not optional:
            break
        worst = max(optional, key=lambda p: p.priority)
        keep.remove(worst)
        dropped.append(worst.name or worst.text[:20])
    text = tf(_join(keep))
    if segments_of(text) > max_segments:
        text = hard_truncate(text, max_segments)
        dropped.append("truncated")
    return text, dropped


def menu_part(options: list[tuple[str, str]], priority: int = 5, name: str = "menu", required: bool = False) -> Part:
    """Numbered options: one per line, with shorter layouts as fallbacks."""
    items = [f"{k} {label}" for k, label in options]
    one = "\n".join(items)
    two = "\n".join("  ".join(items[i:i + 2]) for i in range(0, len(items), 2))
    flat = " ".join(items)
    alts = tuple(x for x in (two, flat) if x != one)
    return Part(one, priority, name, required, alts)


def hard_truncate(text: str, max_segments: int = MAX_SEGMENTS) -> str:
    """Last resort: cut at a word boundary so the text fits."""
    while text and segments_of(text + "..") > max_segments:
        cut = max(text.rfind(" ", 0, len(text) - 1), text.rfind("\n", 0, len(text) - 1))
        text = text[:cut] if cut > 0 else text[:-1]
    return text + ".."
