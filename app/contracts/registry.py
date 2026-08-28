from pydantic import BaseModel

from app.domain.ai import AIContext, AIResponseEnvelope, PromptTemplate
from app.domain.events import DomainEvent
from app.domain.features import InstitutionalFeatureSet, MacroFeatureSet, TechnicalFeatureSet
from app.domain.intelligence import DecisionReport, MarketDataSnapshot
from app.domain.knowledge import KnowledgeRecord, RelationshipRecord
from app.domain.market_data import MarketQuote, OhlcBar
from app.domain.provider_snapshots import (
    COTSnapshot,
    DXYSnapshot,
    EconomicEventSnapshot,
    ETFSnapshot,
    GoldPriceSnapshot,
    NewsEventSnapshot,
)
from app.domain.source_data import (
    InstitutionalSourceBundle,
    MarketSourceBundle,
    SourceReadResult,
)

CONTRACT_MODELS: dict[str, type[BaseModel]] = {
    "ai_context": AIContext,
    "ai_response_envelope": AIResponseEnvelope,
    "cot_snapshot": COTSnapshot,
    "decision_report": DecisionReport,
    "dxy_snapshot": DXYSnapshot,
    "domain_event": DomainEvent,
    "economic_event_snapshot": EconomicEventSnapshot,
    "etf_snapshot": ETFSnapshot,
    "gold_price_snapshot": GoldPriceSnapshot,
    "institutional_source_bundle": InstitutionalSourceBundle,
    "institutional_feature_set": InstitutionalFeatureSet,
    "knowledge_record": KnowledgeRecord,
    "macro_feature_set": MacroFeatureSet,
    "market_source_bundle": MarketSourceBundle,
    "market_data_snapshot": MarketDataSnapshot,
    "market_quote": MarketQuote,
    "news_event_snapshot": NewsEventSnapshot,
    "ohlc_bar": OhlcBar,
    "prompt_template": PromptTemplate,
    "relationship_record": RelationshipRecord,
    "source_read_result": SourceReadResult,
    "technical_feature_set": TechnicalFeatureSet,
}


def export_contract_schemas() -> dict[str, dict]:
    return {name: model.model_json_schema() for name, model in CONTRACT_MODELS.items()}
