"""Small intent classifier: TF-IDF word 1-2 grams + char 2-5 grams, LogisticRegression or calibrated LinearSVC
(whichever wins cross-validation). Trained on data/nlu_training.jsonl."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np

from app.config import ASSETS_DIR, MODELS_DIR, REPORTS_DIR
from app.core import intent_lite

log = logging.getLogger("agahi.intent")
INTENTS = ["PRICE", "FORECAST", "WEATHER", "ADVICE", "ARRIVALS", "COMPARE", "LOCATION", "LANG", "HELP",
           "MENU", "STOP", "START", "SMALLTALK", "UNKNOWN"]
TRAIN_FILE = ASSETS_DIR / "nlu_training.jsonl"
CASUAL_FILE = ASSETS_DIR / "nlu_casual_test.jsonl"
MODEL_PATH = MODELS_DIR / "intent" / "intent.joblib"          # scikit-learn pipeline (training machine only)
LITE_JSON = MODELS_DIR / "intent" / "intent_lite.json"        # NumPy-only copy used by the web app
LITE_NPZ = MODELS_DIR / "intent" / "intent_lite.npz"
SEED = 42
CV_FOLDS = 3
WORD_FEATURES = 8000
CHAR_FEATURES = 30000
_MODEL: dict = {}


def load_examples(path: Path = TRAIN_FILE) -> list[dict]:
    """Read JSONL examples {text, intent, lang, ...}."""
    out = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _features():
    """Word 1-2 grams plus character 2-5 grams (TF-IDF union)."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.pipeline import FeatureUnion
    return FeatureUnion([
        ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), token_pattern=r"(?u)\b\w+\b",
                                 sublinear_tf=True, max_features=WORD_FEATURES)),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True, min_df=2,
                                 max_features=CHAR_FEATURES)),
    ])


def candidates() -> dict:
    """The two classifiers compared by cross-validation."""
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.svm import LinearSVC
    return {
        "logistic_regression": make_pipeline(_features(), LogisticRegression(C=10.0, max_iter=3000, random_state=SEED)),
        "linear_svc_calibrated": make_pipeline(_features(), CalibratedClassifierCV(
            LinearSVC(C=0.5, random_state=SEED), cv=3, method="sigmoid")),
    }


def make_pipeline_model(name: str = "logistic_regression"):
    """One candidate pipeline by name."""
    return candidates()[name]


def train(normalise, run_id: int | None = None) -> dict:
    """Compare candidates by stratified CV on the training split, keep the better one, evaluate on a
    20% hold-out (by language) and on the hand-written casual set, then refit on all data and save."""
    import joblib
    from sklearn.metrics import confusion_matrix
    from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
    ex = load_examples()
    texts = [normalise(e["text"]) for e in ex]
    labels = [e["intent"] for e in ex]
    langs = [e["lang"] for e in ex]
    strat = [f"{l}|{i}" for l, i in zip(langs, labels)]
    idx = np.arange(len(ex))
    tr, te = train_test_split(idx, test_size=0.2, random_state=SEED, stratify=strat)
    Xtr, ytr = [texts[i] for i in tr], [labels[i] for i in tr]
    cv = StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=SEED)
    comparison = {}
    for name, model in candidates().items():
        t0 = time.perf_counter()
        scores = cross_val_score(model, Xtr, ytr, cv=cv, scoring="accuracy")
        comparison[name] = {"cv_accuracy": float(scores.mean()), "cv_std": float(scores.std()),
                            "seconds": round(time.perf_counter() - t0, 1)}
    chosen = max(comparison, key=lambda k: comparison[k]["cv_accuracy"])
    m = make_pipeline_model(chosen).fit(Xtr, ytr)
    pred = m.predict([texts[i] for i in te])
    truth = [labels[i] for i in te]
    acc = float(np.mean([p == t for p, t in zip(pred, truth)]))
    by_lang = {}
    for lg in ("en", "rn", "ne"):
        sel = [k for k, i in enumerate(te) if langs[i] == lg]
        if sel:
            by_lang[lg] = float(np.mean([pred[k] == truth[k] for k in sel]))
    cm = confusion_matrix(truth, pred, labels=INTENTS).tolist()
    final = make_pipeline_model(chosen).fit(texts, labels)
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(final, MODEL_PATH, compress=3)
    intent_lite.export(final, chosen, LITE_JSON, LITE_NPZ)
    casual = load_examples(CASUAL_FILE)
    cpred = final.predict([normalise(c["text"]) for c in casual]) if casual else []
    casual_acc = float(np.mean([p == c["intent"] for p, c in zip(cpred, casual)])) if casual else None
    t0 = time.perf_counter()
    lite = intent_lite.load(LITE_JSON, LITE_NPZ)
    for _ in range(50):
        lite.predict_proba(["golbheda 14 din"])
    ev = {"accuracy": acc, "by_lang": by_lang, "confusion": cm, "labels": INTENTS, "n_train": len(tr),
          "n_test": len(te), "n_total": len(ex), "file_bytes": LITE_JSON.stat().st_size + LITE_NPZ.stat().st_size,
          "sklearn_file_bytes": MODEL_PATH.stat().st_size,
          "inference_ms": (time.perf_counter() - t0) / 50 * 1000, "chosen": chosen, "comparison": comparison,
          "features": f"TF-IDF word 1-2 grams (max {WORD_FEATURES}) + char 2-5 grams (max {CHAR_FEATURES})",
          "casual_classifier_accuracy": casual_acc, "casual_n": len(casual)}
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "intent_eval.json").write_text(json.dumps(ev, indent=1), encoding="utf-8")
    _MODEL.clear()
    return ev


def get_model():
    """The NumPy-only classifier (None if not trained: the NLU then runs on rules alone)."""
    if "m" in _MODEL:
        return _MODEL["m"]
    m = None
    try:
        m = intent_lite.load(LITE_JSON, LITE_NPZ)
    except Exception as e:  # corrupt file -> rule-only NLU
        log.warning("Intent model could not be loaded: %s", e)
    _MODEL["m"] = m
    return m


def predict_proba(text: str) -> dict[str, float]:
    """Intent probabilities, or {} if no model."""
    m = get_model()
    if m is None or not text:
        return {}
    probs = m.predict_proba([text])[0]
    return {c: float(p) for c, p in zip(m.classes_, probs)}
