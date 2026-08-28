import json
import logging
import statistics
from datetime import datetime, UTC
from pathlib import Path
from decimal import Decimal
import pandas as pd
import yfinance as yf

from app.domain.market_data import OhlcBar, Timeframe
from app.domain.intelligence import MarketRegimeAnalysis, ConfidenceScore, MarketRegime, ContractStatus, EngineId, DirectionalBias
from app.application.engines.pullback_risk_engine import PullbackRiskEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PullbackValidator:
    def __init__(self, engine: PullbackRiskEngine | None = None):
        self.engine = engine or PullbackRiskEngine()
        
    def _create_mock_regime(self) -> MarketRegimeAnalysis:
        return MarketRegimeAnalysis(
            engine=EngineId.MARKET_REGIME,
            status=ContractStatus.SUCCESS,
            confidence=ConfidenceScore(value=80, reason="Validation"),
            quality=100,
            score=80,
            regime=MarketRegime.BULL,
            bias=DirectionalBias.BULLISH,
            dynamic_weights={},
            evidence=(),
        )

    def generate_daily_bars(self, hourly_bars: list[OhlcBar]) -> list[OhlcBar]:
        daily_dict = {}
        for b in hourly_bars:
            d = b.timestamp.date()
            if d not in daily_dict:
                daily_dict[d] = []
            daily_dict[d].append(b)
            
        daily_bars = []
        for d, bars_in_day in daily_dict.items():
            daily_bars.append(OhlcBar(
                symbol="XAU/USD",
                provider_symbol="XAU/USD",
                timeframe=Timeframe.ONE_DAY,
                timestamp=datetime(d.year, d.month, d.day, tzinfo=UTC),
                open=bars_in_day[0].open,
                high=max(b.high for b in bars_in_day),
                low=min(b.low for b in bars_in_day),
                close=bars_in_day[-1].close,
                volume=sum(b.volume or Decimal("0") for b in bars_in_day),
                provider="twelve_data"
            ))
        return daily_bars

    def validate(self, bars: list[OhlcBar], lookback: int = 5000, max_forward_window: int = 120, step_hours: int = 4) -> dict[str, dict]:
        bars = sorted(bars, key=lambda b: b.timestamp)
        results_by_bucket = {
            "LOW": [],
            "MEDIUM": [],
            "HIGH": [],
            "EXTREME": []
        }
        
        regime = self._create_mock_regime()
        
        # We need at least lookback bars to form technicals properly (EMA200 needs 200 daily bars, which is ~4800 hourly bars)
        start_idx = lookback
        end_idx = len(bars) - max_forward_window
        
        logger.info(f"Starting validation from index {start_idx} to {end_idx}, step {step_hours}")
        
        for i in range(start_idx, end_idx, step_hours):
            slice_hourly = bars[i-lookback:i+1]
            slice_daily = self.generate_daily_bars(slice_hourly)
            
            all_bars = tuple(slice_hourly + slice_daily)
            report = self.engine.analyze(all_bars, regime)
            
            # forward windows: 24h, 48h, 72h, 120h
            # The prompt asks for 5 trading days. We will use the max forward window (120 bars = 5 days) for the excursion.
            # We can compute excursion at 24h, 48h, 72h, 120h and store all.
            excursions = {}
            current_close = float(slice_hourly[-1].close)
            
            for w_name, w_size in [("24h", 24), ("48h", 48), ("72h", 72), ("5d", 120)]:
                forward_bars = bars[i+1:i+1+w_size]
                if not forward_bars:
                    continue
                min_low = min(float(b.low) for b in forward_bars)
                exc = (current_close - min_low) / current_close if current_close > 0 else 0.0
                excursions[w_name] = max(0.0, exc)
            
            if "5d" in excursions:
                # We group the main results by the max window (5d) as the primary excursion
                results_by_bucket[report.level].append(excursions)

        final_results = {}
        for bucket, ex_list in results_by_bucket.items():
            if not ex_list:
                final_results[bucket] = {
                    "sample_count": 0,
                    "pullback_0_5_pct_hit_rate": 0.0,
                    "pullback_1_0_pct_hit_rate": 0.0,
                    "pullback_2_0_pct_hit_rate": 0.0,
                    "mean_adverse_excursion": 0.0,
                    "median_adverse_excursion": 0.0,
                    "max_adverse_excursion": 0.0
                }
                continue
            
            samples = len(ex_list)
            # using 5d window for the main metrics
            exc_5d = [x["5d"] for x in ex_list]
            
            pb_05 = sum(1 for x in exc_5d if x >= 0.005) / samples
            pb_10 = sum(1 for x in exc_5d if x >= 0.01) / samples
            pb_20 = sum(1 for x in exc_5d if x >= 0.02) / samples
            
            final_results[bucket] = {
                "sample_count": samples,
                "pullback_0_5_pct_hit_rate": round(pb_05, 4),
                "pullback_1_0_pct_hit_rate": round(pb_10, 4),
                "pullback_2_0_pct_hit_rate": round(pb_20, 4),
                "mean_adverse_excursion": round(statistics.mean(exc_5d), 4),
                "median_adverse_excursion": round(statistics.median(exc_5d), 4),
                "max_adverse_excursion": round(max(exc_5d), 4)
            }
            
        return final_results

def fetch_historical_gold(days: int = 730) -> list[OhlcBar]:
    logger.info(f"Fetching {days} days of hourly Gold futures data...")
    df = yf.download('GC=F', period=f'{days}d', interval='1h')
    
    # yf download might return MultiIndex columns if multiple tickers. Let's flatten if so.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
        
    bars = []
    for dt, row in df.iterrows():
        # Clean potential NaNs
        if pd.isna(row['Close']):
            continue
            
        bars.append(OhlcBar(
            symbol="XAU/USD",
            provider_symbol="GC=F",
            timeframe=Timeframe.ONE_HOUR,
            timestamp=dt.to_pydatetime().astimezone(UTC),
            open=Decimal(str(row['Open'])),
            high=Decimal(str(row['High'])),
            low=Decimal(str(row['Low'])),
            close=Decimal(str(row['Close'])),
            volume=Decimal(str(row['Volume'])),
            provider="twelve_data"
        ))
    logger.info(f"Fetched {len(bars)} hourly bars.")
    return bars

def generate_report(results: dict[str, dict]):
    md = "# Pullback Risk Validation Report\n\n"
    md += "This report evaluates the predictive value of the `PullbackRiskScore` using historical gold data.\n\n"
    
    md += "## Methodology\n"
    md += "- **Data**: 730 days of hourly gold futures (`GC=F`).\n"
    md += "- **Forward Window**: 5 trading days.\n"
    md += "- **Adverse Excursion**: Maximum percentage drop from the score timestamp's close.\n\n"
    
    md += "## Results by Risk Bucket\n\n"
    md += "| Bucket | Samples | >= 0.5% Drop | >= 1.0% Drop | >= 2.0% Drop | Mean Drop | Median Drop | Max Drop |\n"
    md += "|--------|---------|--------------|--------------|--------------|-----------|-------------|----------|\n"
    
    for bucket in ["LOW", "MEDIUM", "HIGH", "EXTREME"]:
        res = results.get(bucket, {})
        if not res or res.get("sample_count", 0) == 0:
            md += f"| {bucket} | 0 | - | - | - | - | - | - |\n"
            continue
        
        md += f"| {bucket} | {res['sample_count']} | {res['pullback_0_5_pct_hit_rate']:.1%} | {res['pullback_1_0_pct_hit_rate']:.1%} | {res['pullback_2_0_pct_hit_rate']:.1%} | {res['mean_adverse_excursion']:.2%} | {res['median_adverse_excursion']:.2%} | {res['max_adverse_excursion']:.2%} |\n"
        
    # Check monotonicity
    md += "\n## Monotonicity Check\n"
    
    means = {b: results[b]["mean_adverse_excursion"] for b in ["LOW", "MEDIUM", "HIGH", "EXTREME"] if results.get(b, {}).get("sample_count", 0) > 0}
    
    is_monotonic = True
    if "HIGH" in means and "MEDIUM" in means and means["HIGH"] < means["MEDIUM"]:
        is_monotonic = False
    if "MEDIUM" in means and "LOW" in means and means["MEDIUM"] < means["LOW"]:
        is_monotonic = False
        
    if is_monotonic:
        md += "✅ **Passed**: Higher risk buckets consistently show larger mean adverse excursions.\n"
    else:
        md += "❌ **Failed**: The heuristic is uncalibrated. Higher risk buckets do not consistently show larger mean adverse excursions.\n"
        
    md += "\n## Conclusion\n"
    if is_monotonic and ("HIGH" in means):
        md += "The Pullback Risk Score demonstrates useful separation and predictive value for forward adverse excursions. **Proposal: Proceed to Phase 3 calibration.**\n"
    else:
        md += "The Pullback Risk Score does not demonstrate consistent separation. Individual components (RSI, FVG, Momentum) should be reviewed and recalibrated.\n"
        
    return md

if __name__ == "__main__":
    bars = fetch_historical_gold(730)
    
    validator = PullbackValidator()
    results = validator.validate(bars, step_hours=12)
    
    out_dir = Path("data/pullback_validation")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    with open(out_dir / "results.json", "w") as f:
        json.dump(results, f, indent=2)
        
    doc_dir = Path("docs")
    doc_dir.mkdir(parents=True, exist_ok=True)
    
    report_md = generate_report(results)
    with open(doc_dir / "PULLBACK_VALIDATION_REPORT.md", "w", encoding="utf-8") as f:
        f.write(report_md)
        
    print("Validation complete. Check docs/PULLBACK_VALIDATION_REPORT.md and data/pullback_validation/results.json")
