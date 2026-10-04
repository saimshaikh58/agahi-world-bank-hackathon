"""Auto-generated reports: model_card.md, training_log.txt and the README 'Latest results' block."""
from __future__ import annotations

import json
import re

from app import db
from app.config import REPORTS_DIR, ROOT

README_START, README_END = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"


def _pct(v) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def results_markdown(run_id: int | None = None) -> str:
    """Markdown summary of a model run, built only from saved results."""
    run = db.q1("SELECT * FROM model_runs WHERE id=?", (run_id,)) if run_id else db.q1(
        "SELECT * FROM model_runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1")
    if not run:
        return "_No model run yet. Run the app once or click **Train all**._"
    s = json.loads(run["summary_json"] or "{}")
    ds = db.q1("SELECT * FROM dataset_versions WHERE active=1") or {}
    rep = json.loads(ds.get("report_json") or "{}")
    cells = db.q("SELECT crop, horizon, model, status, skill, coverage, coverage50, dir_acc, n_test FROM backtest_results "
                 "WHERE run_id=? AND chosen=1", (run["id"],))
    order = ["d7", "d14", "d21", "d28", "m1", "m2", "m3"]
    cells.sort(key=lambda c: (c["crop"], order.index(c["horizon"]) if c["horizon"] in order else 99))
    fp = s.get("footprint", {})
    lines = [
        f"Run {run['id']} ({run['mode']} mode), finished {run['finished_at']}. Dataset v{run['data_version']}"
        f"{' (SAMPLE, synthetic)' if ds.get('is_sample') else ''}, prices {rep.get('date_range', ['?', '?'])[0]} to "
        f"{rep.get('date_range', ['?', '?'])[1]}.", "",
        f"- Forecast cells (crop x horizon): {s.get('cells', 0)}; status counts: "
        + ", ".join(f"{k}: {v}" for k, v in sorted(s.get("status_counts", {}).items())),
        f"- Weather weeks 2-4 cells that beat climatology by >= 3%: {s.get('weather_kept', 0)} of {s.get('weather_cells', 0)}",
        f"- Intent classifier held-out accuracy: {_pct(s.get('intent_accuracy'))} ({s.get('intent_model', 'n/a')}); "
        f"hand-written casual set ({s.get('casual_n', 0)} messages, whole NLU): {_pct(s.get('casual_accuracy'))}",
        f"- Model footprint: {fp.get('price_files', 0)} price artifacts, {fp.get('price_bytes', 0) / 1024:.0f} KB total; "
        f"median CPU inference {fp.get('median_inference_ms') or 0:.2f} ms; intent model {s.get('intent_bytes', 0) / 1024:.0f} KB",
        "- Farmers see the shorter 50% range (right about half the time); the wide 80% range is right about 8 times in 10.",
        "", "| crop | horizon | chosen model | status | skill vs best baseline | 80% coverage | 50% coverage | direction acc. | test origins |",
        "|---|---|---|---|---|---|---|---|---|"]
    for c in cells:
        lines.append(f"| {c['crop']} | {c['horizon']} | {c['model']} | {c['status']} | {_pct(c['skill'])} | "
                     f"{_pct(c['coverage'])} | {_pct(c.get('coverage50'))} | {_pct(c['dir_acc'])} | {c['n_test']} |")
    return "\n".join(lines)


def write_all(run_id: int | None = None) -> None:
    """Write model_card.md, training_log.txt and update README."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    md = results_markdown(run_id)
    card = ("# Agahi model card (auto-generated)\n\n"
            "Small models trained on local data: baselines, Ridge, small HistGradientBoosting, split-conformal "
            "intervals, climatology and a TF-IDF + LogisticRegression intent classifier. No LLM at runtime.\n\n"
            "## Latest results\n\n" + md + "\n\n## Intended use\nRough estimates of wholesale price ranges for Kalimati market "
            "and location weather context by SMS. Not farm-gate prices, not financial advice.\n\n## Limitations\n"
            "- Under 4 years of prices: months 1-3 are seasonal outlooks only.\n- Weather beyond about 2 weeks is "
            "climatology.\n- Arrivals include Indian imports.\n- Nepali text needs native review.\n")
    (REPORTS_DIR / "model_card.md").write_text(card, encoding="utf-8")
    write_footprint()
    job = db.q1("SELECT log FROM jobs WHERE kind='train' ORDER BY id DESC LIMIT 1")
    if job and job["log"]:
        (REPORTS_DIR / "training_log.txt").write_text(job["log"], encoding="utf-8")
    update_readme(md)


def update_readme(md: str) -> None:
    """Rewrite the block between the RESULTS markers."""
    path = ROOT / "README.md"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if README_START not in text or README_END not in text:
        return
    new = re.sub(re.escape(README_START) + r".*?" + re.escape(README_END),
                 lambda m: f"{README_START}\n{md}\n{README_END}", text, flags=re.S)
    path.write_text(new, encoding="utf-8")


def write_footprint() -> None:
    """reports/footprint.json: size and CPU time of every runtime model file (read by the model guide)."""
    from app.config import MODELS_DIR
    from app.forecast.predict import footprint
    fp = footprint()
    intent = [MODELS_DIR / "intent" / n for n in ("intent_lite.json", "intent_lite.npz")]
    weather = list((MODELS_DIR / "weather").glob("*.joblib"))
    ev_path = REPORTS_DIR / "intent_eval.json"
    ev = json.loads(ev_path.read_text(encoding="utf-8")) if ev_path.exists() else {}
    fp.update(intent_bytes=sum(p.stat().st_size for p in intent if p.exists()),
              intent_inference_ms=ev.get("inference_ms"),
              weather_files=len(weather), weather_bytes=sum(p.stat().st_size for p in weather),
              is_sample=bool(db.get_meta("is_sample", False)))
    (REPORTS_DIR / "footprint.json").write_text(json.dumps(fp, indent=1), encoding="utf-8")
