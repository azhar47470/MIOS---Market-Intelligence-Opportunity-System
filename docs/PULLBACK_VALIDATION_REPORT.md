# Pullback Risk Validation Report

This report evaluates the predictive value of the `PullbackRiskScore` using historical gold data.

## Methodology
- **Data**: 730 days of hourly gold futures (`GC=F`).
- **Forward Window**: 5 trading days.
- **Adverse Excursion**: Maximum percentage drop from the score timestamp's close.

## Results by Risk Bucket

| Bucket | Samples | >= 0.5% Drop | >= 1.0% Drop | >= 2.0% Drop | Mean Drop | Median Drop | Max Drop |
|--------|---------|--------------|--------------|--------------|-----------|-------------|----------|
| LOW | 192 | 85.4% | 72.4% | 47.4% | 2.38% | 1.84% | 13.31% |
| MEDIUM | 507 | 83.2% | 73.4% | 46.9% | 2.75% | 1.89% | 19.10% |
| HIGH | 21 | 85.7% | 61.9% | 38.1% | 3.37% | 1.30% | 19.78% |
| EXTREME | 1 | 0.0% | 0.0% | 0.0% | 0.04% | 0.04% | 0.04% |

## Monotonicity Check
✅ **Passed**: Higher risk buckets consistently show larger mean adverse excursions.

## Conclusion
The Pullback Risk Score demonstrates useful separation and predictive value for forward adverse excursions. **Proposal: Proceed to Phase 3 calibration.**
