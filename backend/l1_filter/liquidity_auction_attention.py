"""S106 attention overlay for sweep-anchored FVG/IFVG signals.

The global daily regime and the closed 4h trend remain hard directional gates
inside the FVG state machine.  Intraday OI, taker flow and relative volume are
used here as position-sizing evidence instead of three binary entry gates.
Only simultaneous opposition from both taker-flow measurements is a veto.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class LiquidityAuctionAttentionConfig:
    minimum_risk_scale: float = 0.25
    risk_step_per_confirmation: float = 0.25
    long_opposition_taker_ratio: float = 0.48
    short_opposition_taker_ratio: float = 0.52
    veto_dual_opposing_taker: bool = True

    def validate(self) -> None:
        if not 0 < self.minimum_risk_scale <= 1:
            raise ValueError('Invalid minimum attention risk scale')
        if not 0 <= self.risk_step_per_confirmation <= 1:
            raise ValueError('Invalid attention risk step')
        if not (0 < self.long_opposition_taker_ratio < 0.5
                < self.short_opposition_taker_ratio < 1):
            raise ValueError('Invalid opposing-flow thresholds')


def apply_liquidity_auction_attention(
    signals: list[dict],
    config: LiquidityAuctionAttentionConfig = LiquidityAuctionAttentionConfig(),
) -> tuple[list[dict], dict]:
    """Apply a causal attention-based size and opposing-flow veto."""
    config.validate()
    accepted = []
    diagnostics = Counter(input_signals=len(signals))
    for signal in signals:
        side = int(signal['side'])
        evidence = dict(signal.get('evidence') or {})
        candle_taker = float(evidence.get('taker_ratio', np.nan))
        archive_taker = float(
            evidence.get('archive_taker_buy_sell_ratio', np.nan))
        if side == 1:
            opposing = (
                np.isfinite(candle_taker) and np.isfinite(archive_taker)
                and candle_taker <= config.long_opposition_taker_ratio
                and archive_taker < 1.0)
        else:
            opposing = (
                np.isfinite(candle_taker) and np.isfinite(archive_taker)
                and candle_taker >= config.short_opposition_taker_ratio
                and archive_taker > 1.0)
        if config.veto_dual_opposing_taker and opposing:
            diagnostics['dual_opposing_taker_veto'] += 1
            continue

        micro_score = int(evidence.get('micro_score', 0))
        if not 0 <= micro_score <= 3:
            raise ValueError('Signal micro score must be between zero and three')
        risk_scale = min(
            1.0,
            config.minimum_risk_scale
            + config.risk_step_per_confirmation * micro_score,
        )
        tagged = dict(signal)
        tagged['risk_scale'] = risk_scale
        route = str(evidence.get('route', 'UNKNOWN')).lower()
        tagged['setup'] = f'liquidity_attention_{route}'
        tagged['evidence'] = {
            **evidence,
            'attention_micro_score': micro_score,
            'attention_risk_scale': risk_scale,
            'dual_opposing_taker': bool(opposing),
        }
        accepted.append(tagged)
        diagnostics[f'accepted_micro_{micro_score}'] += 1
        diagnostics[f'accepted_risk_{risk_scale:.2f}'] += 1
    diagnostics['accepted_signals'] = len(accepted)
    diagnostics['config'] = {
        'minimum_risk_scale': config.minimum_risk_scale,
        'risk_step_per_confirmation': config.risk_step_per_confirmation,
        'long_opposition_taker_ratio': config.long_opposition_taker_ratio,
        'short_opposition_taker_ratio': config.short_opposition_taker_ratio,
        'veto_dual_opposing_taker': config.veto_dual_opposing_taker,
    }
    return accepted, dict(diagnostics)
