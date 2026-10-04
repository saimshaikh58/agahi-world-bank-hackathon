"""Calibrated 50% range: covers about half of backtest cases; display range never wider than the 80% range."""
import numpy as np

from app.core.replies import display_range
from app.forecast import conformal


def test_fifty_percent_range_covers_half_on_synthetic_data():
    rng = np.random.default_rng(7)
    n = 4000
    actual = rng.normal(0, 0.1, n) + rng.standard_t(5, n) * 0.05
    pred = actual + rng.normal(0, 0.08, n)
    fold = np.repeat(np.arange(20), n // 20)
    lo, hi = conformal.sequential_intervals(pred, actual, fold, conformal.LO50_Q, conformal.HI50_Q)
    m = np.isfinite(lo)
    cov = np.mean((actual[m] >= lo[m]) & (actual[m] <= hi[m]))
    assert abs(cov - 0.5) <= 0.05, cov
    lo8, hi8 = conformal.sequential_intervals(pred, actual, fold)
    cov8 = np.mean((actual[m] >= lo8[m]) & (actual[m] <= hi8[m]))
    assert abs(cov8 - 0.8) <= 0.05, cov8
    assert np.all(hi[m] - lo[m] <= hi8[m] - lo8[m] + 1e-12)


def test_display_range_never_wider_than_80_and_clipped():
    rng = np.random.default_rng(3)
    for _ in range(2000):
        p50 = rng.uniform(5, 200)
        p10, p90 = p50 * rng.uniform(0.3, 0.95), p50 * rng.uniform(1.05, 2.5)
        p25, p75 = p10 + (p50 - p10) * rng.uniform(0.2, 1), p50 + (p90 - p50) * rng.uniform(0, 0.8)
        f = dict(p10=p10, p25=p25, p50=p50, p75=p75, p90=p90,
                 band_lo=p50 * rng.uniform(0.2, 1.0), band_hi=p50 * rng.uniform(1.0, 3.0))
        lo, hi = display_range(f)
        assert lo >= 0 and lo <= hi
        assert lo % 5 == 0 and hi % 5 == 0
        assert hi - lo <= p90 - p10 + 1e-9
        assert lo >= p10 - 1e-9 or lo == hi
        assert hi <= p90 + 1e-9 or lo == hi
