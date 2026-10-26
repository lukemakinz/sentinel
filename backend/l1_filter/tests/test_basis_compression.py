import pandas as pd

from l1_filter.basis_compression import BasisCompressionConfig, basis_compression_signals


def test_same_timestamp_funding_is_not_used_for_signal():
    timestamp = pd.Timestamp('2026-01-02T00:00:00Z')
    features = pd.DataFrame({
        'basis': [0.02], 'median': [0.0], 'q95': [0.005],
        'mad': [0.001], 'score': [20.0],
    }, index=[timestamp])
    funding = pd.Series([0.001], index=[timestamp])
    assert basis_compression_signals(features, funding, 'ETHUSDT') == []


def test_only_prior_realized_positive_funding_qualifies():
    timestamp = pd.Timestamp('2026-01-02T00:00:00Z')
    features = pd.DataFrame({
        'basis': [0.02], 'median': [0.0], 'q95': [0.005],
        'mad': [0.001], 'score': [20.0],
    }, index=[timestamp])
    funding = pd.Series([0.001], index=[timestamp - pd.Timedelta(hours=8)])
    signals = basis_compression_signals(features, funding, 'ETHUSDT')
    assert len(signals) == 1
    assert signals[0]['timestamp'] == timestamp
