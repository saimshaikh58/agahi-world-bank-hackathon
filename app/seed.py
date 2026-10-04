"""Demo conversations: ~300 messages over 14 days through the real engine, all marked demo=1."""
from __future__ import annotations

import random
from datetime import timedelta

from app import db, locations
from app.core.engine import handle_message
from app.util import now

SEED = 11
DAYS = 14
SCRIPTS = {
    "en": [["hello", "1", "{loc}", "1", "1", "2"], ["hi", "1", "{loc}", "tomato price", "tomato 14 days", "3"],
           ["potato", "potato 2 weeks", "should i sell potato 300kg"], ["weather", "2", "0", "2", "4", "3"],
           ["onion price", "next month rain", "what is cricket score"], ["cauliflower forecast", "1", "5"]],
    "rn": [["namaste", "1", "{loc}", "1", "2"], ["golbheda", "golbheda 14 din", "becham golbheda 500kg"],
           ["alu ko bhau", "alu 2 hapta", "mausam"], ["kauli kati", "1", "6", "0", "3", "1"],
           ["pyaj", "ghatcha?", "bus kati baje"], ["5", "1", "0", "9", "2"]],
    "ne": [["नमस्ते", "1", "{loc}", "1", "1"], ["गोलभेडा", "गोलभेडा १४ दिन", "मौसम"], ["आलुको भाउ", "आलु बेच्ने कि राख्ने"],
           ["काउली", "अर्को महिना वर्षा"], ["२", "२", "३"]],
}
LANG_SHARE = (("rn", 0.5), ("en", 0.25), ("ne", 0.25))


def demo_rows() -> int:
    """Count of demo message rows."""
    r = db.q1("SELECT COUNT(*) AS n FROM messages WHERE demo=1")
    return int(r["n"]) if r else 0


def seed_demo(n_farmers: int = 40, force: bool = False) -> int:
    """Create demo farmers and conversations. Idempotent unless force."""
    if demo_rows() and not force:
        return 0
    rng = random.Random(SEED)
    locs = [l for l in locations.selectable()]
    if not locs:
        return 0
    base = now() - timedelta(days=DAYS)
    count = 0
    for i in range(n_farmers):
        r = rng.random()
        lang = "rn" if r < 0.5 else "en" if r < 0.75 else "ne"
        phone = f"+97798500{i:05d}"
        loc_n = str(rng.randint(1, len(locs) + 1))
        latest = now() - timedelta(hours=3)
        t = base.replace(hour=0, minute=0, second=0) + timedelta(days=rng.randint(0, DAYS - 1),
                                                                 hours=rng.choice([6, 7, 8, 9, 12, 16, 17, 18, 19]))
        t = min(t, latest - timedelta(hours=1))
        sessions = [rng.choice(SCRIPTS[lang][:2])] + [rng.choice(SCRIPTS[lang][2:]) for _ in range(rng.randint(1, 3))]
        for k, script in enumerate(sessions):
            if k:
                t = t + timedelta(days=rng.uniform(0.5, 4), minutes=rng.randint(0, 300))
                if t > latest:
                    break
            for j, msg in enumerate(script):
                ts = (t + timedelta(minutes=j * 2)).replace(microsecond=0).isoformat()
                handle_message("web", phone, msg.format(loc=loc_n), offline=True, demo=True, ts=ts)
                count += 2
        if i % 9 == 0 and t + timedelta(minutes=30) < now():
            ts = (t + timedelta(minutes=30)).replace(microsecond=0).isoformat()
            handle_message("web", phone, "stop", offline=True, demo=True, ts=ts)
            count += 2
    db.x("UPDATE farmers SET demo=1 WHERE phone LIKE '+97798500%'")
    return count


def purge_demo() -> int:
    """Delete all demo rows."""
    n = demo_rows()
    with db.connect() as c:
        c.execute("DELETE FROM messages WHERE demo=1")
        c.execute("DELETE FROM sessions WHERE phone IN (SELECT phone FROM farmers WHERE demo=1)")
        c.execute("DELETE FROM farmers WHERE demo=1")
        c.execute("DELETE FROM outbox WHERE demo=1")
    return n
