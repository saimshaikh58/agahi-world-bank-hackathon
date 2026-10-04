import numpy as np
import pandas as pd

from app.forecast import backtest, conformal
from app.forecast.features import FEATURES, build_features, build_target


def frame(n=900, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-01", periods=n, freq="D")
    p = 50 * np.exp(np.cumsum(rng.normal(0, 0.03, n)))
    return pd.DataFrame({"price": p, "price2": p * 1.1, "arrivals": rng.uniform(1e4, 5e4, n),
                         "rain": rng.gamma(1, 5, n), "tmax": rng.normal(25, 3, n)}, index=idx)


def test_features_do_not_leak():
    f = frame()
    t = f.index[500]
    a = build_features(f).loc[t]
    g = f.copy()
    g.loc[g.index > t, ["price", "arrivals", "rain", "tmax", "price2"]] *= 3.7
    b = build_features(g).loc[t]
    pd.testing.assert_series_equal(a, b)


def test_folds_respect_embargo():
    dates = pd.date_range("2022-01-01", periods=1000, freq="D")
    for gap in (7, 28, 93):
        for tr, te in backtest.make_folds(dates, gap, 30):
            assert dates[tr].max() + pd.Timedelta(days=gap) < dates[te].min()
            assert set(tr).isdisjoint(te)


def test_conformal_coverage_close_to_nominal():
    rng = np.random.default_rng(1)
    n = 3000
    pred = rng.normal(0, 1, n)
    actual = pred + rng.normal(0, 0.5, n)
    fold = np.repeat(np.arange(30), n // 30)
    lo, hi = conformal.sequential_intervals(pred, actual, fold)
    m = np.isfinite(lo)
    cov = np.mean((actual[m] >= lo[m]) & (actual[m] <= hi[m]))
    assert abs(cov - 0.8) <= 0.05


def _run(y_fn, seed):
    rng = np.random.default_rng(seed)
    n = 1200
    idx = pd.date_range("2021-01-01", periods=n, freq="D")
    X = pd.DataFrame(rng.normal(0, 1, (n, len(FEATURES))), index=idx, columns=FEATURES)
    y = pd.Series(y_fn(X, rng), index=idx)
    wf = backtest.walk_forward(X, y, 7, "fast")
    base = wf["best_baseline"]
    base_mae = backtest._mae(wf["preds"][base], y.values, wf["tested"])
    p0 = np.full(n, 50.0)
    mets = {k: backtest.metrics(v, y.values, wf["fold"], p0, base_mae) for k, v in wf["preds"].items()}
    chosen = min(mets, key=lambda k: mets[k]["mae_log"])
    return backtest.decide_status(chosen, mets[chosen], "d7"), chosen


def test_gate_no_signal_is_pattern_only():
    status, chosen = _run(lambda X, rng: rng.normal(0, 0.1, len(X)), 3)
    assert status == "pattern only", chosen


def test_gate_planted_signal_is_reliable():
    status, chosen = _run(lambda X, rng: 0.2 * X["ret7"].values + rng.normal(0, 0.05, len(X)), 4)
    assert status == "reliable", chosen


def test_month_horizons_never_reliable():
    great = dict(skill=0.5, dir_acc=0.9, coverage=0.8, n_test=500)
    assert backtest.decide_status("ridge", great, "d7") == "reliable"
    for h in ("m1", "m2", "m3"):
        assert backtest.decide_status("ridge", great, h) == "indicative"


def test_target_month_uses_window():
    f = frame()
    y = build_target(f, "m1")
    t = 100
    expect = np.log(f["price"].iloc[t + 27:t + 34].mean() / f["price"].iloc[t])
    assert abs(y.iloc[t] - expect) < 1e-9
