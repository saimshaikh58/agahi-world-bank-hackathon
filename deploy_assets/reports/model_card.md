# Agahi model card (auto-generated)

Small models trained on local data: baselines, Ridge, small HistGradientBoosting, split-conformal intervals, climatology and a TF-IDF + LogisticRegression intent classifier. No LLM at runtime.

## Latest results

Run 9 (fast mode), finished 2026-10-04T17:22:45+05:45. Dataset v1, prices 2023-08-01 to 2026-10-03.

- Forecast cells (crop x horizon): 91; status counts: indicative: 25, pattern only: 50, reliable: 16
- Weather weeks 2-4 cells that beat climatology by >= 3%: 0 of 84
- Intent classifier held-out accuracy: 99.4% (logistic_regression); hand-written casual set (162 messages, whole NLU): 97.5%
- Model footprint: 91 price artifacts, 1991 KB total; median CPU inference 0.66 ms; intent model 981 KB
- Farmers see the shorter 50% range (right about half the time); the wide 80% range is right about 8 times in 10.

| crop | horizon | chosen model | status | skill vs best baseline | 80% coverage | 50% coverage | direction acc. | test origins |
|---|---|---|---|---|---|---|---|---|
| beans | d7 | blend | indicative | 0.1% | 72.3% | 45.2% | 57.7% | 788 |
| beans | d14 | mean_reversion | pattern only | 0.0% | 67.8% | 42.3% | 64.0% | 781 |
| beans | d21 | mean_reversion | pattern only | 0.0% | 66.5% | 41.5% | 68.4% | 774 |
| beans | d28 | mean_reversion | pattern only | 0.0% | 65.1% | 42.0% | 70.8% | 767 |
| beans | m1 | mean_reversion | pattern only | 0.0% | 61.4% | 44.2% | 71.2% | 762 |
| beans | m2 | mean_reversion | pattern only | 0.0% | 68.9% | 42.3% | 68.9% | 732 |
| beans | m3 | mean_reversion | pattern only | 0.0% | 62.3% | 38.8% | 66.7% | 702 |
| bitter_gourd | d7 | hgb | indicative | 4.6% | 79.1% | 55.6% | 66.3% | 788 |
| bitter_gourd | d14 | hgb | reliable | 5.7% | 74.5% | 46.5% | 67.0% | 781 |
| bitter_gourd | d21 | hgb | reliable | 11.6% | 75.2% | 41.6% | 69.2% | 774 |
| bitter_gourd | d28 | ridge | pattern only | 18.6% | 69.2% | 37.1% | 72.3% | 767 |
| bitter_gourd | m1 | ridge | pattern only | 23.3% | 64.8% | 33.5% | 76.0% | 762 |
| bitter_gourd | m2 | ridge | pattern only | 29.5% | 69.3% | 38.4% | 85.3% | 732 |
| bitter_gourd | m3 | ridge | pattern only | 25.5% | 60.4% | 35.0% | 82.3% | 702 |
| cabbage | d7 | persistence | pattern only | 0.0% | 77.6% | 49.3% | 0.0% | 788 |
| cabbage | d14 | blend | indicative | 0.4% | 72.4% | 43.4% | 30.2% | 781 |
| cabbage | d21 | blend | indicative | 2.0% | 72.7% | 43.4% | 39.2% | 774 |
| cabbage | d28 | blend | indicative | 0.5% | 74.5% | 39.7% | 31.1% | 767 |
| cabbage | m1 | persistence | pattern only | 0.0% | 72.1% | 37.7% | 0.0% | 762 |
| cabbage | m2 | hgb | indicative | 16.2% | 75.4% | 54.9% | 74.7% | 732 |
| cabbage | m3 | hgb | indicative | 12.0% | 72.9% | 43.0% | 75.7% | 702 |
| carrot | d7 | persistence | pattern only | 0.0% | 80.8% | 55.5% | 0.0% | 788 |
| carrot | d14 | hgb | indicative | 4.4% | 77.1% | 54.8% | 69.7% | 781 |
| carrot | d21 | hgb | reliable | 8.3% | 81.8% | 54.2% | 74.8% | 774 |
| carrot | d28 | blend | reliable | 8.5% | 80.8% | 52.3% | 77.0% | 767 |
| carrot | m1 | hgb | indicative | 9.0% | 82.9% | 53.4% | 77.4% | 762 |
| carrot | m2 | hgb | indicative | 10.5% | 86.3% | 70.4% | 81.4% | 732 |
| carrot | m3 | hgb | indicative | 6.0% | 81.6% | 68.5% | 82.7% | 702 |
| cauliflower | d7 | hgb | reliable | 6.4% | 75.5% | 43.5% | 64.9% | 788 |
| cauliflower | d14 | hgb | reliable | 10.0% | 73.6% | 42.0% | 68.6% | 781 |
| cauliflower | d21 | hgb | reliable | 6.8% | 76.5% | 53.1% | 69.0% | 774 |
| cauliflower | d28 | hgb | reliable | 8.0% | 78.1% | 56.6% | 71.7% | 767 |
| cauliflower | m1 | hgb | indicative | 12.5% | 77.8% | 52.3% | 75.0% | 762 |
| cauliflower | m2 | blend | indicative | 10.7% | 81.1% | 50.4% | 73.2% | 732 |
| cauliflower | m3 | hgb | indicative | 21.8% | 88.0% | 69.6% | 86.9% | 702 |
| eggplant | d7 | hgb | indicative | 1.6% | 78.4% | 46.6% | 65.0% | 788 |
| eggplant | d14 | mean_reversion | pattern only | 0.0% | 76.0% | 42.9% | 65.5% | 781 |
| eggplant | d21 | mean_reversion | pattern only | 0.0% | 74.5% | 50.6% | 64.5% | 774 |
| eggplant | d28 | mean_reversion | pattern only | 0.0% | 73.4% | 54.3% | 66.1% | 767 |
| eggplant | m1 | mean_reversion | pattern only | 0.0% | 74.1% | 55.8% | 66.0% | 762 |
| eggplant | m2 | mean_reversion | pattern only | 0.0% | 68.3% | 47.9% | 67.9% | 732 |
| eggplant | m3 | mean_reversion | pattern only | 0.0% | 67.4% | 40.3% | 60.3% | 702 |
| okra | d7 | hgb | reliable | 5.6% | 79.7% | 48.4% | 66.3% | 788 |
| okra | d14 | hgb | reliable | 9.0% | 78.4% | 45.9% | 66.0% | 781 |
| okra | d21 | hgb | reliable | 13.4% | 78.6% | 52.7% | 72.9% | 774 |
| okra | d28 | blend | reliable | 19.0% | 78.5% | 53.2% | 75.5% | 767 |
| okra | m1 | blend | indicative | 19.7% | 78.8% | 49.0% | 73.9% | 762 |
| okra | m2 | hgb | pattern only | 16.2% | 69.5% | 42.1% | 83.5% | 732 |
| okra | m3 | ridge | indicative | 20.9% | 76.6% | 50.0% | 84.6% | 702 |
| onion_dry | d7 | persistence | pattern only | 0.0% | 83.7% | 58.0% | 0.0% | 788 |
| onion_dry | d14 | persistence | pattern only | 0.0% | 85.0% | 54.9% | 0.0% | 781 |
| onion_dry | d21 | persistence | pattern only | 0.0% | 80.4% | 53.4% | 0.0% | 774 |
| onion_dry | d28 | persistence | pattern only | 0.0% | 75.7% | 56.2% | 0.0% | 767 |
| onion_dry | m1 | persistence | pattern only | 0.0% | 74.8% | 54.3% | 0.0% | 762 |
| onion_dry | m2 | persistence | pattern only | 0.0% | 60.0% | 39.4% | 0.0% | 732 |
| onion_dry | m3 | persistence | pattern only | 0.0% | 64.5% | 33.2% | 0.0% | 702 |
| peas | d7 | persistence | pattern only | 0.0% | 80.3% | 55.0% | 0.0% | 537 |
| peas | d14 | hgb | indicative | 4.2% | 81.0% | 60.4% | 66.0% | 535 |
| peas | d21 | hgb | reliable | 12.1% | 78.6% | 55.1% | 70.8% | 518 |
| peas | d28 | hgb | reliable | 18.7% | 79.1% | 58.0% | 79.3% | 505 |
| peas | m1 | hgb | indicative | 19.3% | 81.1% | 57.5% | 80.0% | 500 |
| peas | m2 | hgb | indicative | 35.8% | 77.7% | 62.0% | 90.3% | 450 |
| peas | m3 | ridge | pattern only | 13.2% | 49.8% | 25.1% | 87.5% | 299 |
| potato | d7 | mean_reversion | pattern only | 0.0% | 72.9% | 41.9% | 70.8% | 788 |
| potato | d14 | blend | pattern only | 0.6% | 69.5% | 39.5% | 77.9% | 781 |
| potato | d21 | hgb | reliable | 12.9% | 71.3% | 46.9% | 79.1% | 774 |
| potato | d28 | hgb | pattern only | 7.2% | 69.6% | 42.0% | 73.7% | 767 |
| potato | m1 | blend | pattern only | 9.0% | 67.8% | 39.5% | 85.8% | 762 |
| potato | m2 | seasonal_naive | pattern only | 0.0% | 61.0% | 38.2% | 87.4% | 732 |
| potato | m3 | seasonal_naive | pattern only | 0.0% | 68.7% | 41.7% | 85.4% | 702 |
| pumpkin | d7 | persistence | pattern only | 0.0% | 85.6% | 59.2% | 0.0% | 788 |
| pumpkin | d14 | persistence | pattern only | 0.0% | 85.4% | 57.7% | 0.0% | 781 |
| pumpkin | d21 | persistence | pattern only | 0.0% | 82.5% | 60.9% | 0.0% | 774 |
| pumpkin | d28 | persistence | pattern only | 0.0% | 81.8% | 59.7% | 0.0% | 767 |
| pumpkin | m1 | mean_reversion | pattern only | 0.0% | 79.1% | 51.1% | 62.4% | 762 |
| pumpkin | m2 | mean_reversion | pattern only | 0.0% | 75.7% | 49.4% | 61.6% | 732 |
| pumpkin | m3 | mean_reversion | pattern only | 0.0% | 71.5% | 39.6% | 70.4% | 702 |
| radish | d7 | persistence | pattern only | 0.0% | 80.9% | 51.7% | 0.0% | 784 |
| radish | d14 | persistence | pattern only | 0.0% | 76.7% | 49.5% | 0.0% | 777 |
| radish | d21 | blend | indicative | 0.6% | 77.2% | 51.4% | 46.3% | 770 |
| radish | d28 | persistence | pattern only | 0.0% | 72.5% | 51.5% | 0.0% | 763 |
| radish | m1 | persistence | pattern only | 0.0% | 72.4% | 52.0% | 0.0% | 760 |
| radish | m2 | ridge | pattern only | 18.5% | 66.1% | 37.5% | 67.4% | 730 |
| radish | m3 | ridge | pattern only | 30.7% | 68.0% | 43.6% | 72.7% | 700 |
| tomato | d7 | hgb | indicative | 4.4% | 78.4% | 50.6% | 59.0% | 718 |
| tomato | d14 | persistence | pattern only | 0.0% | 83.5% | 49.2% | 0.0% | 704 |
| tomato | d21 | hgb | indicative | 3.3% | 80.2% | 51.7% | 68.4% | 690 |
| tomato | d28 | hgb | reliable | 7.9% | 80.4% | 53.4% | 71.0% | 676 |
| tomato | m1 | hgb | indicative | 12.2% | 78.7% | 52.2% | 74.5% | 669 |
| tomato | m2 | ridge | indicative | 12.9% | 71.8% | 35.8% | 82.3% | 627 |
| tomato | m3 | mean_reversion | pattern only | 0.0% | 79.1% | 53.3% | 68.6% | 597 |

## Intended use
Rough estimates of wholesale price ranges for Kalimati market and location weather context by SMS. Not farm-gate prices, not financial advice.

## Limitations
- Under 4 years of prices: months 1-3 are seasonal outlooks only.
- Weather beyond about 2 weeks is climatology.
- Arrivals include Indian imports.
- Nepali text needs native review.
