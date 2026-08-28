"""Decision adapter base class — pure presentation over the UnifiedDecision."""

from abc import ABC, abstractmethod

from app.domain.decisions import UnifiedDecision


class DecisionAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Adapter identifier, e.g. "forex", "physical", "etf"."""

    @abstractmethod
    def adapt(self, unified: UnifiedDecision, spot: float | None = None):
        """Re-express the unified outlook for one kind of user."""
