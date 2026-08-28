"""Forex adapter — presents the outlook as a trading signal (today's output)."""

from app.application.adapters.base import DecisionAdapter
from app.domain.decisions import ForexDecision, UnifiedDecision

SIGNAL_BY_BIAS = {"BULLISH": "LONG", "BEARISH": "SHORT", "NEUTRAL": "WAIT"}


class ForexAdapter(DecisionAdapter):
    def __init__(self, stop_pct: float = 0.02, target_pct: float = 0.04) -> None:
        self.stop_pct = stop_pct
        self.target_pct = target_pct

    @property
    def name(self) -> str:
        return "forex"

    def adapt(self, unified: UnifiedDecision, spot: float | None = None) -> ForexDecision:
        signal = SIGNAL_BY_BIAS.get(unified.market_bias.value, "WAIT")
        entry = round(spot, 2) if spot else None
        take_profit = stop_loss = None
        if spot:
            if signal == "LONG":
                take_profit = round(spot * (1 + self.target_pct), 2)
                stop_loss = round(spot * (1 - self.stop_pct), 2)
            elif signal == "SHORT":
                take_profit = round(spot * (1 - self.target_pct), 2)
                stop_loss = round(spot * (1 + self.stop_pct), 2)
        return ForexDecision(
            signal=signal,
            confidence=unified.confidence,
            entry=entry,
            take_profit=take_profit,
            stop_loss=stop_loss,
            risk=unified.risk,
            horizon=unified.horizon_label,
            reasoning=unified.reasoning,
            timestamp=unified.timestamp,
        )
