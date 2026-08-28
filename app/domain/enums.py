from enum import StrEnum


class Recommendation(StrEnum):
    STRONG_BUY = "Strong Buy"
    BUY = "Buy"
    HOLD = "Hold"
    WAIT = "Wait"
    TAKE_PROFIT = "Take Profit"
    STRONG_SELL = "Strong Sell"

    @property
    def label(self) -> str:
        emoji_by_recommendation = {
            Recommendation.STRONG_BUY: "\U0001f7e2",
            Recommendation.BUY: "\U0001f7e2",
            Recommendation.HOLD: "\U0001f7e1",
            Recommendation.WAIT: "\u26aa",
            Recommendation.TAKE_PROFIT: "\U0001f7e0",
            Recommendation.STRONG_SELL: "\U0001f534",
        }
        return f"{emoji_by_recommendation[self]} {self.value}"


class AlertTrigger(StrEnum):
    INITIAL_SNAPSHOT = "initial_snapshot"
    RECOMMENDATION_CHANGED = "recommendation_changed"
    CONFIDENCE_CHANGED_SIGNIFICANTLY = "confidence_changed_significantly"
    MAJOR_MACRO_EVENT = "major_macro_event"
    MAJOR_GEOPOLITICAL_EVENT = "major_geopolitical_event"
    HIGH_PRIORITY_RISK = "high_priority_risk"
    CONSOLIDATED_UPDATE = "consolidated_update"


class MarketEventKind(StrEnum):
    MACROECONOMIC = "macroeconomic"
    GEOPOLITICAL = "geopolitical"
    RISK_WARNING = "risk_warning"
    BREAKING_NEWS = "breaking_news"


class NotificationKind(StrEnum):
    RECOMMENDATION_ALERT = "recommendation_alert"
    DAILY_MARKET_SUMMARY = "daily_market_summary"
    WEEKLY_INTELLIGENCE_REPORT = "weekly_intelligence_report"
    BREAKING_NEWS_ALERT = "breaking_news_alert"
    MAJOR_ECONOMIC_EVENT_ALERT = "major_economic_event_alert"
    SYSTEM_HEALTH_NOTIFICATION = "system_health_notification"
    ENGINE_STATUS_NOTIFICATION = "engine_status_notification"


class NotificationPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class DeliveryStatus(StrEnum):
    SENT = "sent"
    SUPPRESSED = "suppressed"
    CONSOLIDATED = "consolidated"
    FAILED = "failed"
