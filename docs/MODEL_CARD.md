# Model card (template)

The full, auto-generated card with the latest numbers is written to `reports/model_card.md` after every training run and can be downloaded from the Models page. This file explains how to read it.

## Models
| Task | Model | Size | Notes |
|---|---|---|---|
| Price, 7 to 28 days | best of persistence, seasonal-naive, mean reversion, Ridge, HistGradientBoosting (median), blend | about 20 to 50 KB each | chosen per crop x horizon by walk-forward MAE |
| Price, months 1 to 3 | same candidates, 7-day mean target | same | never above `indicative` |
| Price intervals | split-conformal on out-of-fold residuals | a few numbers | 80% nominal |
| Weather days 1 to 7 | Open-Meteo (external) | none | climatology fallback |
| Weather weeks 2 to 4 | Ridge on anomalies vs climatology | a few KB | kept only with at least 3% skill |
| Weather months 1 to 3 | empirical climatology, terciles | none | always labelled climatology |
| Intent | TF-IDF char 2-4 grams + logistic regression | under 1 MB | 20% stratified hold-out |

## Data
Kalimati daily wholesale prices (anchor series, primary variant per crop), daily arrivals, and daily GEE weather per district and for the whole area.

## Evaluation
Walk-forward backtests with an embargo of h days; metrics: MAE (log and Rs/kg), MAPE, direction accuracy (moves of at least 2%), skill vs the best baseline, pinball loss, 80% interval coverage and width, number of test origins. Every production forecast is logged to `forecast_ledger` and scored when the realised price arrives.

## Intended use and limits
Indicative ranges to help plan harvest and sales. Not farm-gate prices, not financial advice. See the README limitations.
