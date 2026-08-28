from decimal import Decimal

from app.domain.features import (
    AsianRangeSignal,
    FairValueGap,
    LiquiditySweep,
    OrderBlock,
    PremiumDiscountZone,
    StructureSignal,
    SwingPoint,
    TechnicalFeatureSet,
    TechnicalSignalDirection,
)
from app.domain.market_data import OhlcBar, Timeframe


def build_technical_features(bars: tuple[OhlcBar, ...]) -> TechnicalFeatureSet:
    if len(bars) < 5:
        return TechnicalFeatureSet(candle_count=len(bars))
    primary_bars = _primary_bars(bars)
    ordered = tuple(sorted(primary_bars, key=lambda bar: bar.timestamp))
    if len(ordered) < 5:
        return TechnicalFeatureSet(candle_count=len(ordered))
        
    closes = [bar.close for bar in ordered]
    highs = [bar.high for bar in ordered]
    lows = [bar.low for bar in ordered]
    latest_close = closes[-1]
    latest_timestamp = ordered[-1].timestamp
    
    short_ma = _average(closes[-5:])
    long_window = closes[-20:] if len(closes) >= 20 else closes
    long_ma = _average(long_window)
    atr = _average([high - low for high, low in zip(highs[-14:], lows[-14:], strict=False)])
    
    momentum_pct = ((latest_close - closes[-5]) / closes[-5]) * Decimal("100")
    swing_highs, swing_lows = _swings(ordered)
    support = min(lows[-20:] if len(lows) >= 20 else lows)
    resistance = max(highs[-20:] if len(highs) >= 20 else highs)
    
    structure_signal = _detect_structure_signal(ordered)
    order_block = _detect_order_block(ordered)
    
    # Daily context calculations
    daily_bars = tuple(sorted([b for b in bars if b.timeframe == Timeframe.ONE_DAY], key=lambda b: b.timestamp))
    daily_trend = None
    rsi_14 = None
    ema_200 = None
    if len(daily_bars) > 0:
        daily_closes = [b.close for b in daily_bars]
        daily_trend = _trend_bias(daily_bars)
        rsi_14 = _rsi(daily_closes, 14)
        ema_200_list = _ema(daily_closes, 200)
        ema_200 = ema_200_list[-1] if ema_200_list else None
    
    return TechnicalFeatureSet(
        candle_count=len(ordered),
        latest_timestamp=latest_timestamp,
        latest_close=latest_close,
        rsi_14=rsi_14,
        ema_200=ema_200,
        daily_trend=daily_trend,
        short_moving_average=short_ma,
        long_moving_average=long_ma,
        average_true_range=atr,
        momentum_percent=momentum_pct,
        trend_quality=_trend_quality(
            short_ma, long_ma, atr, _multi_timeframe_aligned(bars)
        ),
        support=support,
        support_confidence=_level_confidence(ordered, support, atr, is_support=True),
        resistance=resistance,
        resistance_confidence=_level_confidence(ordered, resistance, atr, is_support=False),
        swing_highs=tuple(
            SwingPoint(candle_index=index, price=price) for index, price in swing_highs[-8:]
        ),
        swing_lows=tuple(
            SwingPoint(candle_index=index, price=price) for index, price in swing_lows[-8:]
        ),
        structure_signal=structure_signal,
        fair_value_gaps=_detect_fair_value_gaps(ordered),
        order_block=order_block,
        breaker_block=_detect_breaker_block(ordered, order_block),
        mitigation_block=_detect_mitigation_block(ordered, order_block),
        liquidity_sweep=_detect_liquidity_sweep(ordered, swing_highs, swing_lows),
        premium_discount=_premium_discount_zone(support, resistance, latest_close),
        asian_range=_detect_asian_range(ordered),
        volume_ratio=_volume_features(ordered)[0],
        volume_confirmation=_volume_features(ordered)[1],
        vwap=_volume_features(ordered)[2],
        volatility_regime=_volatility_regime(atr, latest_close),
        timeframe_biases=_timeframe_biases(bars),
        multi_timeframe_aligned=_multi_timeframe_aligned(bars),
        higher_timeframe_confirmed=_higher_timeframe_confirmed(_timeframe_biases(bars)),
    )

def _primary_bars(bars: tuple[OhlcBar, ...]) -> tuple[OhlcBar, ...]:
    h1_bars = tuple(bar for bar in bars if bar.timeframe == Timeframe.ONE_HOUR)
    return h1_bars or bars


def _detect_structure_signal(bars: tuple[OhlcBar, ...]) -> StructureSignal | None:
    if len(bars) < 7:
        return None
    swing_highs, swing_lows = _swings(bars)
    latest_close = bars[-1].close
    previous_highs = [item for item in swing_highs if item[0] < len(bars) - 1]
    previous_lows = [item for item in swing_lows if item[0] < len(bars) - 1]
    if previous_highs and latest_close > previous_highs[-1][1]:
        signal_type = "CHOCH" if _prior_structure_bias(swing_highs, swing_lows) == "down" else "BOS"
        return StructureSignal(
            signal_type=signal_type,
            direction=TechnicalSignalDirection.BULLISH,
            broken_level=previous_highs[-1][1],
            close=latest_close,
        )
    if previous_lows and latest_close < previous_lows[-1][1]:
        signal_type = "CHOCH" if _prior_structure_bias(swing_highs, swing_lows) == "up" else "BOS"
        return StructureSignal(
            signal_type=signal_type,
            direction=TechnicalSignalDirection.BEARISH,
            broken_level=previous_lows[-1][1],
            close=latest_close,
        )
    return None


def _swings(
    bars: tuple[OhlcBar, ...],
) -> tuple[list[tuple[int, Decimal]], list[tuple[int, Decimal]]]:
    swing_highs: list[tuple[int, Decimal]] = []
    swing_lows: list[tuple[int, Decimal]] = []
    for index in range(1, len(bars) - 1):
        previous_bar = bars[index - 1]
        current_bar = bars[index]
        next_bar = bars[index + 1]
        if current_bar.high > previous_bar.high and current_bar.high > next_bar.high:
            swing_highs.append((index, current_bar.high))
        if current_bar.low < previous_bar.low and current_bar.low < next_bar.low:
            swing_lows.append((index, current_bar.low))
    return swing_highs, swing_lows


def _prior_structure_bias(
    swing_highs: list[tuple[int, Decimal]], swing_lows: list[tuple[int, Decimal]]
) -> str:
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        highs_falling = swing_highs[-1][1] < swing_highs[-2][1]
        lows_falling = swing_lows[-1][1] < swing_lows[-2][1]
        highs_rising = swing_highs[-1][1] > swing_highs[-2][1]
        lows_rising = swing_lows[-1][1] > swing_lows[-2][1]
        if highs_falling and lows_falling:
            return "down"
        if highs_rising and lows_rising:
            return "up"
    return "unknown"


def _detect_fair_value_gaps(bars: tuple[OhlcBar, ...]) -> tuple[FairValueGap, ...]:
    gaps: list[FairValueGap] = []
    for index in range(2, len(bars)):
        first = bars[index - 2]
        third = bars[index]
        if third.low > first.high:
            gaps.append(
                FairValueGap(
                    direction=TechnicalSignalDirection.BULLISH,
                    lower_bound=first.high,
                    upper_bound=third.low,
                )
            )
        elif third.high < first.low:
            gaps.append(
                FairValueGap(
                    direction=TechnicalSignalDirection.BEARISH,
                    lower_bound=third.high,
                    upper_bound=first.low,
                )
            )
    return tuple(gaps[-5:])


def _detect_order_block(bars: tuple[OhlcBar, ...]) -> OrderBlock | None:
    structure = _detect_structure_signal(bars)
    if structure is None:
        return None
    recent = tuple(reversed(bars[-12:-1]))
    if structure.direction == TechnicalSignalDirection.BULLISH:
        candidate = next((bar for bar in recent if bar.close < bar.open), None)
    else:
        candidate = next((bar for bar in recent if bar.close > bar.open), None)
    if candidate is None:
        return None
    return OrderBlock(direction=structure.direction, low=candidate.low, high=candidate.high)


def _detect_breaker_block(
    bars: tuple[OhlcBar, ...], order_block: OrderBlock | None
) -> OrderBlock | None:
    """Classify a reclaimed opposite candle zone after a confirmed structure break."""
    if order_block is None:
        return None
    latest = bars[-1]
    if (
        order_block.direction == TechnicalSignalDirection.BULLISH
        and latest.close > order_block.high
    ):
        return order_block.model_copy(update={"block_type": "BREAKER_BLOCK"})
    if order_block.direction == TechnicalSignalDirection.BEARISH and latest.close < order_block.low:
        return order_block.model_copy(update={"block_type": "BREAKER_BLOCK"})
    return None


def _detect_mitigation_block(
    bars: tuple[OhlcBar, ...], order_block: OrderBlock | None
) -> OrderBlock | None:
    """Mark a block only when price is currently trading back through its zone."""
    if order_block is None:
        return None
    latest_close = bars[-1].close
    if order_block.low <= latest_close <= order_block.high:
        return order_block.model_copy(
            update={"block_type": "MITIGATION_BLOCK", "mitigated": True}
        )
    return None


def _detect_liquidity_sweep(
    bars: tuple[OhlcBar, ...],
    swing_highs: list[tuple[int, Decimal]],
    swing_lows: list[tuple[int, Decimal]],
) -> LiquiditySweep | None:
    if not bars:
        return None
    latest = bars[-1]
    prior_highs = [price for index, price in swing_highs if index < len(bars) - 1]
    prior_lows = [price for index, price in swing_lows if index < len(bars) - 1]
    if prior_highs and latest.high > prior_highs[-1] and latest.close < prior_highs[-1]:
        return LiquiditySweep(
            direction=TechnicalSignalDirection.BEARISH,
            swept_level=prior_highs[-1],
            close=latest.close,
        )
    if prior_lows and latest.low < prior_lows[-1] and latest.close > prior_lows[-1]:
        return LiquiditySweep(
            direction=TechnicalSignalDirection.BULLISH,
            swept_level=prior_lows[-1],
            close=latest.close,
        )
    return None


def _premium_discount_zone(
    range_low: Decimal, range_high: Decimal, latest_close: Decimal
) -> PremiumDiscountZone:
    equilibrium = (range_low + range_high) / Decimal("2")
    zone = "EQUILIBRIUM"
    if latest_close < equilibrium:
        zone = "DISCOUNT"
    elif latest_close > equilibrium:
        zone = "PREMIUM"
    return PremiumDiscountZone(
        range_low=range_low,
        equilibrium=equilibrium,
        range_high=range_high,
        current_zone=zone,
    )


def _volume_features(
    bars: tuple[OhlcBar, ...]
) -> tuple[Decimal | None, TechnicalSignalDirection, Decimal | None]:
    window = bars[-20:]
    if not window or any(bar.volume is None for bar in window):
        return None, TechnicalSignalDirection.NEUTRAL, None
    volumes = [bar.volume for bar in window if bar.volume is not None]
    volume_total = sum(volumes, Decimal("0"))
    if volume_total == 0:
        return None, TechnicalSignalDirection.NEUTRAL, None
    vwap = sum((bar.close * bar.volume for bar in window if bar.volume is not None), Decimal("0"))
    vwap /= volume_total
    recent_volumes = volumes[-6:-1]
    if not recent_volumes:
        return None, TechnicalSignalDirection.NEUTRAL, vwap
    ratio = volumes[-1] / _average(recent_volumes)
    latest = window[-1]
    if ratio >= Decimal("1.20") and latest.close > latest.open:
        return ratio, TechnicalSignalDirection.BULLISH, vwap
    if ratio >= Decimal("1.20") and latest.close < latest.open:
        return ratio, TechnicalSignalDirection.BEARISH, vwap
    return ratio, TechnicalSignalDirection.NEUTRAL, vwap


def _volatility_regime(atr: Decimal, latest_close: Decimal) -> str:
    ratio = atr / latest_close if latest_close else Decimal("0")
    if ratio >= Decimal("0.008"):
        return "HIGH"
    if ratio <= Decimal("0.002"):
        return "LOW"
    return "NORMAL"


def _trend_quality(
    short_ma: Decimal,
    long_ma: Decimal,
    atr: Decimal,
    multi_timeframe_aligned: bool,
) -> int:
    if atr <= 0:
        return 0
    normalized_spread = abs(short_ma - long_ma) / atr
    score = min(85, int(normalized_spread * Decimal("25")))
    if multi_timeframe_aligned:
        score += 15
    return max(0, min(100, score))


def _level_confidence(
    bars: tuple[OhlcBar, ...], level: Decimal, atr: Decimal, *, is_support: bool
) -> int:
    tolerance = max(atr * Decimal("0.20"), Decimal("0.01"))
    touches = sum(
        1
        for bar in bars[-20:]
        if abs((bar.low if is_support else bar.high) - level) <= tolerance
    )
    return min(100, 35 + (touches * 20))


def _detect_asian_range(bars: tuple[OhlcBar, ...]) -> AsianRangeSignal | None:
    latest = bars[-1]
    session_bars = tuple(
        bar
        for bar in bars
        if bar.timestamp.date() == latest.timestamp.date() and 0 <= bar.timestamp.hour < 6
    )
    if not session_bars:
        return None
    high = max(bar.high for bar in session_bars)
    low = min(bar.low for bar in session_bars)
    breakout = TechnicalSignalDirection.NEUTRAL
    if latest.close > high:
        breakout = TechnicalSignalDirection.BULLISH
    elif latest.close < low:
        breakout = TechnicalSignalDirection.BEARISH
    return AsianRangeSignal(high=high, low=low, breakout_direction=breakout)


def _timeframe_biases(bars: tuple[OhlcBar, ...]) -> dict[str, TechnicalSignalDirection]:
    biases: dict[str, TechnicalSignalDirection] = {}
    for timeframe in {bar.timeframe for bar in bars}:
        timeframe_bars = tuple(bar for bar in bars if bar.timeframe == timeframe)
        biases[timeframe.value] = _trend_bias(timeframe_bars)
    return biases


def _multi_timeframe_aligned(bars: tuple[OhlcBar, ...]) -> bool:
    biases = _timeframe_biases(bars)
    actionable = {
        bias for bias in biases.values() if bias != TechnicalSignalDirection.NEUTRAL
    }
    return len(biases) >= 2 and len(actionable) == 1


def _higher_timeframe_confirmed(
    biases: dict[str, TechnicalSignalDirection],
) -> bool:
    h1_bias = biases.get(Timeframe.ONE_HOUR.value)
    h4_bias = biases.get(Timeframe.FOUR_HOURS.value)
    return (
        h1_bias is not None
        and h4_bias is not None
        and h1_bias == h4_bias
        and h1_bias != TechnicalSignalDirection.NEUTRAL
    )


def _trend_bias(bars: tuple[OhlcBar, ...]) -> TechnicalSignalDirection:
    if len(bars) < 5:
        return TechnicalSignalDirection.NEUTRAL
    ordered = tuple(sorted(bars, key=lambda bar: bar.timestamp))
    closes = [bar.close for bar in ordered]
    short_ma = _average(closes[-5:])
    long_ma = _average(closes[-20:] if len(closes) >= 20 else closes)
    if short_ma > long_ma:
        return TechnicalSignalDirection.BULLISH
    if short_ma < long_ma:
        return TechnicalSignalDirection.BEARISH
    return TechnicalSignalDirection.NEUTRAL


def _average(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))

def _ema(values: list[Decimal], n: int) -> list[Decimal | None]:
    if len(values) < n:
        return [None] * len(values)
    k = Decimal("2.0") / Decimal(n + 1)
    out = [None] * (n - 1)
    prev = sum(values[:n]) / Decimal(n)
    out.append(prev)
    for v in values[n:]:
        prev = v * k + prev * (Decimal("1.0") - k)
        out.append(prev)
    return out

def _rsi(values: list[Decimal], n: int = 14) -> Decimal | None:
    if len(values) < n + 1:
        return None
    gains = Decimal("0")
    losses = Decimal("0")
    for i in range(1, n + 1):
        d = values[i] - values[i - 1]
        gains += max(d, Decimal("0"))
        losses += max(-d, Decimal("0"))
    ag = gains / Decimal(n)
    al = losses / Decimal(n)
    for i in range(n + 1, len(values)):
        d = values[i] - values[i - 1]
        ag = (ag * Decimal(n - 1) + max(d, Decimal("0"))) / Decimal(n)
        al = (al * Decimal(n - 1) + max(-d, Decimal("0"))) / Decimal(n)
    if al == Decimal("0"):
        return Decimal("100")
    rs = ag / al
    return Decimal("100") - (Decimal("100") / (Decimal("1") + rs))
