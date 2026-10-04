"""NumPy-only copy of the trained intent classifier, so the web app runs without scikit-learn
(keeps the Vercel bundle small). Exported from the scikit-learn pipeline at training time and checked
against it in tests. Reproduces TfidfVectorizer (word and char_wb analyzers, sublinear tf, idf, l2),
FeatureUnion, LogisticRegression (softmax) and CalibratedClassifierCV(LinearSVC, sigmoid)."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np

WS = re.compile(r"\s\s+")


class _Vectorizer:
    def __init__(self, spec: dict, idf: np.ndarray) -> None:
        self.analyzer = spec["analyzer"]
        self.lo, self.hi = spec["ngram_range"]
        self.pattern = re.compile(spec.get("token_pattern") or r"(?u)\b\w\w+\b")
        self.vocab = spec["vocabulary"]
        self.sublinear = spec["sublinear_tf"]
        self.idf = idf

    def _grams(self, text: str) -> list[str]:
        text = text.lower()
        if self.analyzer == "word":
            toks = self.pattern.findall(text)
            out = []
            for n in range(self.lo, self.hi + 1):
                out += [" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1)]
            return out
        text = WS.sub(" ", text)
        out = []
        for w in text.split():
            w = " " + w + " "
            for n in range(self.lo, self.hi + 1):
                off = 0
                out.append(w[off:off + n])
                while off + n < len(w):
                    off += 1
                    out.append(w[off:off + n])
                if off == 0:
                    break
        return out

    def transform(self, text: str) -> np.ndarray:
        v = np.zeros(len(self.idf))
        for g in self._grams(text):
            j = self.vocab.get(g)
            if j is not None:
                v[j] += 1.0
        if self.sublinear:
            nz = v > 0
            v[nz] = 1.0 + np.log(v[nz])
        v *= self.idf
        n = math.sqrt(float(v @ v))
        return v / n if n > 0 else v


class IntentLite:
    """predict_proba for one text, same output as the scikit-learn pipeline."""

    def __init__(self, meta: dict, arrays: dict) -> None:
        self.classes_ = np.array(meta["classes"])
        self.kind = meta["kind"]
        self.vecs = [_Vectorizer(spec, arrays[f"idf_{i}"]) for i, spec in enumerate(meta["vectorizers"])]
        self.arrays = arrays
        self.folds = meta.get("folds", 0)

    def _x(self, text: str) -> np.ndarray:
        return np.concatenate([v.transform(text) for v in self.vecs])

    def predict_proba(self, texts: list[str]) -> np.ndarray:
        out = []
        for text in texts:
            x = self._x(text)
            if self.kind == "logistic_regression":
                z = self.arrays["coef"] @ x + self.arrays["intercept"]
                z = np.exp(z - z.max())
                out.append(z / z.sum())
            else:
                acc = np.zeros(len(self.classes_))
                for k in range(self.folds):
                    d = self.arrays[f"coef_{k}"] @ x + self.arrays[f"intercept_{k}"]
                    p = 1.0 / (1.0 + np.exp(self.arrays[f"a_{k}"] * d + self.arrays[f"b_{k}"]))
                    s = p.sum()
                    acc += p / s if s > 0 else np.full(len(p), 1.0 / len(p))
                out.append(acc / self.folds)
        return np.array(out)


def export(pipeline, kind: str, json_path: Path, npz_path: Path) -> None:
    """Write a fitted scikit-learn pipeline (FeatureUnion + classifier) as JSON + NPZ."""
    union, clf = pipeline.steps[0][1], pipeline.steps[-1][1]
    specs, arrays = [], {}
    for i, (_, vec) in enumerate(union.transformer_list):
        specs.append({"analyzer": vec.analyzer, "ngram_range": list(vec.ngram_range), "token_pattern": vec.token_pattern,
                      "sublinear_tf": bool(vec.sublinear_tf), "vocabulary": {k: int(v) for k, v in vec.vocabulary_.items()}})
        arrays[f"idf_{i}"] = vec.idf_.astype(np.float64)
    meta = {"kind": kind, "classes": [str(c) for c in clf.classes_], "vectorizers": specs}
    if kind == "logistic_regression":
        arrays["coef"], arrays["intercept"] = clf.coef_, clf.intercept_
    else:
        cals = clf.calibrated_classifiers_
        meta["folds"] = len(cals)
        for k, cc in enumerate(cals):
            est = cc.estimator
            arrays[f"coef_{k}"], arrays[f"intercept_{k}"] = est.coef_, est.intercept_
            arrays[f"a_{k}"] = np.array([c.a_ for c in cc.calibrators])
            arrays[f"b_{k}"] = np.array([c.b_ for c in cc.calibrators])
    json_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    np.savez_compressed(npz_path, **{k: np.asarray(v, dtype=np.float32) for k, v in arrays.items()})


def load(json_path: Path, npz_path: Path) -> IntentLite | None:
    """Load the exported model, or None if it is not there."""
    if not (json_path.exists() and npz_path.exists()):
        return None
    meta = json.loads(json_path.read_text(encoding="utf-8"))
    with np.load(npz_path) as z:
        arrays = {k: z[k].astype(np.float64) for k in z.files}
    return IntentLite(meta, arrays)
