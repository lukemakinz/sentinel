"""
Base analyst class and signal data structures.
All analysts inherit from BaseAnalyst and produce AnalystSignal instances.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class Bias(str, Enum):
    LONG = 'LONG'
    SHORT = 'SHORT'
    NEUTRAL = 'NEUTRAL'


@dataclass
class AnalystSignal:
    """Output of every analyst module."""
    analyst_name: str
    symbol: str
    score: float  # -100 to +100
    bias: Bias
    confidence: float  # 0.0 to 1.0
    reasoning: str
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        self.score = max(-100, min(100, self.score))
        self.confidence = max(0, min(1, self.confidence))
        if self.score > 0:
            self.bias = Bias.LONG
        elif self.score < 0:
            self.bias = Bias.SHORT
        else:
            self.bias = Bias.NEUTRAL

    def to_dict(self):
        d = asdict(self)
        d['bias'] = self.bias.value
        return d


class BaseAnalyst(ABC):
    """Abstract base class for all analyst modules."""

    name: str = 'base'

    @abstractmethod
    def analyze(self, symbol: str) -> AnalystSignal:
        """
        Run analysis for a given symbol.
        Returns an AnalystSignal with score, bias, confidence, and reasoning.
        """
        pass

    def _neutral_signal(self, symbol: str, reason: str = 'Insufficient data') -> AnalystSignal:
        """Return a neutral signal when analysis cannot be performed."""
        return AnalystSignal(
            analyst_name=self.name,
            symbol=symbol,
            score=0,
            bias=Bias.NEUTRAL,
            confidence=0.0,
            reasoning=reason,
        )
