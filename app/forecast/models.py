"""Small learnable models: Ridge (standardised) and HistGradientBoosting with quantile loss."""
from __future__ import annotations

from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import RidgeCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

SEED = 42
RIDGE_ALPHAS = (0.1, 1.0, 10.0, 100.0, 1000.0)


def make_ridge():
    """Imputer + scaler + RidgeCV (alpha by efficient leave-one-out on the training window)."""
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), RidgeCV(alphas=RIDGE_ALPHAS))


def make_hgb(mode: str, quantile: float = 0.5):
    """Small gradient boosting regressor (median by default)."""
    return HistGradientBoostingRegressor(
        loss="quantile", quantile=quantile, max_depth=3, learning_rate=0.05,
        max_iter=60 if mode == "fast" else 200, l2_regularization=1.0, min_samples_leaf=30, random_state=SEED)
