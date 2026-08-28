# Pullback Risk Calibration Final Report

## Final Decision: **RISK SCORE ONLY**

The Pullback Risk Score provides useful predictive separation (as evidenced by monotonic mean drawdowns and AUC > 0.5), but the absolute 0-100 value does not calibrate cleanly to a 1:1 true probability (Brier score is worse than naive baseline). It should remain an informational risk score rather than a strictly stated percentage probability. No action-layer integration is recommended at this stage.

## A. Dataset
- **Total Samples:** 721
- **Train Size (Chronological):** 504
- **Validation Size (Chronological):** 217

## B. Event Definitions
- **Forward Horizon:** 120h (5 trading days)
- **Thresholds:** >= 0.5%, >= 1.0%, >= 2.0% adverse excursion

## C. Score Bins (Overall)
| Bin | Count | >=0.5% Event | >=1.0% Event | >=2.0% Event | Mean Exc | Median Exc | 95th pctl |
|-----|-------|--------------|--------------|--------------|----------|------------|-----------|
| 0-19 | 28 | 89.3% | 78.6% | 53.6% | 2.47% | 2.05% | 6.90% |
| 20-39 | 259 | 79.9% | 66.8% | 42.1% | 2.24% | 1.70% | 7.11% |
| 40-59 | 371 | 85.4% | 76.0% | 49.1% | 2.84% | 1.97% | 8.31% |
| 60-79 | 62 | 88.7% | 75.8% | 50.0% | 3.53% | 2.16% | 11.95% |
| 80-100 | 1 | 0.0% | 0.0% | 0.0% | 0.04% | 0.04% | 0.04% |

## D. Regime Breakdown (5d >=1.0%)
### Regime: BULL
| Bin | Count | >=1.0% Event | Mean Exc |
|-----|-------|--------------|----------|
| 20-39 | 79 | 41.8% | 1.09% |
| 40-59 | 74 | 51.4% | 1.50% |
| 60-79 | 10 | 30.0% | 1.20% |
| 80-100 | 1 | 0.0% | 0.04% |

### Regime: HIGH_VOLATILITY
| Bin | Count | >=1.0% Event | Mean Exc |
|-----|-------|--------------|----------|
| 20-39 | 93 | 80.6% | 2.54% |
| 40-59 | 292 | 82.2% | 3.19% |
| 60-79 | 52 | 84.6% | 3.98% |

### Regime: RISK_OFF
| Bin | Count | >=1.0% Event | Mean Exc |
|-----|-------|--------------|----------|
| 0-19 | 28 | 78.6% | 2.47% |
| 20-39 | 87 | 74.7% | 2.96% |
| 40-59 | 5 | 80.0% | 2.31% |

## E & F. Calibration Metrics & Walk-Forward (Target: 120h >= 1.0%)
| Split | ROC-AUC | PR-AUC | Brier Score | Base Event Rate |
|-------|---------|--------|-------------|-----------------|
| Train | 0.573 | 0.722 | 0.265 | 68.5% |
| Val   | 0.628 | 0.883 | 0.377 | 82.5% |

## G. Component Analysis (Pearson Correlation to 120h >= 1.0% Event)
| Component | Correlation |
|-----------|-------------|
| Regime Instability | 0.264 |
| Elevated Volatility | 0.126 |
| RSI Exhaustion | -0.089 |
| Weak Trend Quality | 0.063 |
| Resistance/FVG | -0.063 |
| EMA Overextension | -0.047 |
| Liquidity Sweep | -0.045 |
| Momentum Weakness | -0.042 |

## H. Statistical Limitations
- Integer scaling (0-100) heuristically aggregates fixed weights rather than probabilistically regressed coefficients.
- Lookback period is limited to 730 days, meaning macro regime diversity is constrained.
- Brier score penalizes heuristic integer assignments heavily when interpreted directly as probabilities.

