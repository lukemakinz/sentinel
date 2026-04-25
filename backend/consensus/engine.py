"""
Consensus Engine — aggregates analyst signals using weighted voting.
Only generates actionable signals when conviction threshold and minimum agreement are met.
"""
import logging
from django.conf import settings

from analysts.models import AnalystSignalRecord
from .models import ConsensusSignal

logger = logging.getLogger(__name__)

ANALYST_NAMES = ['momentum', 'volume_flow', 'structure', 'sentiment', 'llm_narrative', 'cross_asset']


def get_tier(abs_score):
    if abs_score >= 85:
        return 'HIGH_CONVICTION'
    elif abs_score >= 75:
        return 'SIGNAL'
    elif abs_score >= 65:
        return 'WATCH'
    return 'NONE'


class ConsensusEngine:
    """Weighted consensus engine that aggregates analyst signals."""

    def __init__(self):
        self.weights = settings.CONSENSUS_WEIGHTS
        self.threshold = settings.CONSENSUS_THRESHOLD
        self.min_agreement = settings.CONSENSUS_MIN_AGREEMENT

    def evaluate(self, symbol: str) -> ConsensusSignal:
        """Run consensus evaluation for a symbol using latest analyst signals."""
        signals = {}
        for name in ANALYST_NAMES:
            latest = AnalystSignalRecord.objects.filter(
                analyst_name=name, symbol=symbol,
            ).order_by('-timestamp').first()

            if latest:
                signals[name] = {
                    'score': latest.score,
                    'bias': latest.bias,
                    'confidence': latest.confidence,
                    'reasoning': latest.reasoning[:200],
                }

        if not signals:
            return self._create_signal(symbol, 0, signals, 0)

        # Weighted score
        conviction = 0
        for name, data in signals.items():
            weight = self.weights.get(name, 0)
            conviction += data['score'] * weight

        # Count agreeing analysts
        direction = 'LONG' if conviction > 0 else 'SHORT' if conviction < 0 else 'NEUTRAL'
        agreeing = sum(
            1 for s in signals.values()
            if s['bias'] == direction
        )

        # Apply minimum agreement filter
        abs_score = abs(conviction)
        if agreeing < self.min_agreement:
            tier = 'NONE'
        else:
            tier = get_tier(abs_score)

        consensus = self._create_signal(symbol, conviction, signals, agreeing)
        consensus.tier = tier

        if tier in ('SIGNAL', 'HIGH_CONVICTION'):
            logger.info(f"🎯 {symbol} {tier}: {conviction:+.1f} ({agreeing}/{len(signals)} agree)")

        return consensus

    def _create_signal(self, symbol, conviction, signals, agreeing):
        """Create and save a ConsensusSignal."""
        direction = 'LONG' if conviction > 0 else 'SHORT' if conviction < 0 else 'NEUTRAL'

        return ConsensusSignal.objects.create(
            symbol=symbol,
            conviction_score=conviction,
            bias=direction,
            tier=get_tier(abs(conviction)) if agreeing >= self.min_agreement else 'NONE',
            agreeing_analysts=agreeing,
            total_analysts=len(signals),
            momentum_score=signals.get('momentum', {}).get('score', 0),
            volume_flow_score=signals.get('volume_flow', {}).get('score', 0),
            structure_score=signals.get('structure', {}).get('score', 0),
            sentiment_score=signals.get('sentiment', {}).get('score', 0),
            llm_narrative_score=signals.get('llm_narrative', {}).get('score', 0),
            cross_asset_score=signals.get('cross_asset', {}).get('score', 0),
            analyst_details=signals,
        )

    def evaluate_all(self):
        """Evaluate consensus for all configured trading pairs."""
        results = {}
        for symbol in settings.TRADING_PAIRS:
            try:
                results[symbol] = self.evaluate(symbol)
            except Exception as e:
                logger.error(f"Consensus error {symbol}: {e}")
        return results
