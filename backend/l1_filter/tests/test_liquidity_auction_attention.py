import pytest

from l1_filter.liquidity_auction_attention import (
    LiquidityAuctionAttentionConfig,
    apply_liquidity_auction_attention,
)


def _signal(side=1, micro_score=1, candle_taker=0.51, archive_taker=1.01):
    return {
        'timestamp': '2026-01-01T00:00:00Z',
        'side': side,
        'setup': 'fvg_ifvg_defense',
        'evidence': {
            'route': 'DEFENSE', 'micro_score': micro_score,
            'taker_ratio': candle_taker,
            'archive_taker_buy_sell_ratio': archive_taker,
        },
    }


@pytest.mark.parametrize('micro_score,expected', [
    (0, 0.25), (1, 0.50), (2, 0.75), (3, 1.0),
])
def test_attention_score_scales_risk_in_four_predeclared_steps(
    micro_score, expected,
):
    accepted, diagnostics = apply_liquidity_auction_attention(
        [_signal(micro_score=micro_score)])
    assert accepted[0]['risk_scale'] == expected
    assert accepted[0]['evidence']['attention_risk_scale'] == expected
    assert diagnostics['accepted_signals'] == 1


def test_dual_opposing_taker_vetoes_long():
    accepted, diagnostics = apply_liquidity_auction_attention([
        _signal(side=1, candle_taker=0.47, archive_taker=0.90),
    ])
    assert accepted == []
    assert diagnostics['dual_opposing_taker_veto'] == 1


def test_single_noisy_taker_measurement_does_not_veto():
    accepted, _ = apply_liquidity_auction_attention([
        _signal(side=-1, candle_taker=0.55, archive_taker=0.95),
    ])
    assert len(accepted) == 1


def test_invalid_attention_scale_is_rejected():
    with pytest.raises(ValueError):
        apply_liquidity_auction_attention(
            [_signal()], LiquidityAuctionAttentionConfig(minimum_risk_scale=0))
