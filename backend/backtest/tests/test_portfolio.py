from datetime import datetime, timezone
from unittest.mock import patch

from django.test import TestCase

from backtest.metrics import BacktestMetrics
from backtest.portfolio import run_portfolio_backtest


class PortfolioBacktestTest(TestCase):
    def test_portfolio_combines_symbol_metrics(self):
        metrics_a = BacktestMetrics.from_trades(
            [{'pnl': 10, 'pnl_pct': 10.0}],
            [50, 60],
            initial_capital=50,
        )
        metrics_b = BacktestMetrics.from_trades(
            [{'pnl': -5, 'pnl_pct': -5.0}],
            [50, 45],
            initial_capital=50,
        )

        with patch('backtest.portfolio.BacktestSimulator') as sim_cls:
            sim_cls.side_effect = [
                _fake_simulator(metrics_a),
                _fake_simulator(metrics_b),
            ]
            result = run_portfolio_backtest(
                ['AAA', 'BBB'],
                'S1C',
                datetime(2025, 1, 1, tzinfo=timezone.utc),
                datetime(2025, 2, 1, tzinfo=timezone.utc),
                initial_capital=100.0,
            )

        self.assertEqual(result.combined.total_trades, 2)
        self.assertAlmostEqual(result.combined.total_pnl, 5.0, places=2)
        self.assertEqual(set(result.per_symbol.keys()), {'AAA', 'BBB'})

    def test_portfolio_uses_custom_weights(self):
        seen_capitals = []

        def _capture_cfg(cfg):
            seen_capitals.append((cfg.symbol, cfg.initial_capital))
            metrics = BacktestMetrics.from_trades([], [cfg.initial_capital], initial_capital=cfg.initial_capital)
            return _fake_simulator(metrics)

        with patch('backtest.portfolio.BacktestSimulator', side_effect=_capture_cfg):
            run_portfolio_backtest(
                ['AAA', 'BBB'],
                'S1C',
                datetime(2025, 1, 1, tzinfo=timezone.utc),
                datetime(2025, 2, 1, tzinfo=timezone.utc),
                initial_capital=100.0,
                weights={'AAA': 0.7, 'BBB': 0.3},
            )

        self.assertEqual(seen_capitals, [('AAA', 70.0), ('BBB', 30.0)])

    def test_portfolio_regime_mode_uses_dynamic_weights(self):
        seen_capitals = []

        def _capture_cfg(cfg):
            seen_capitals.append((cfg.symbol, cfg.initial_capital))
            metrics = BacktestMetrics.from_trades([], [cfg.initial_capital], initial_capital=cfg.initial_capital)
            return _fake_simulator(metrics)

        with patch('backtest.portfolio._regime_weights', return_value={'AAA': 0.8, 'BBB': 0.2}):
            with patch('backtest.portfolio.BacktestSimulator', side_effect=_capture_cfg):
                run_portfolio_backtest(
                    ['AAA', 'BBB'],
                    'S1C',
                    datetime(2025, 1, 1, tzinfo=timezone.utc),
                    datetime(2025, 2, 1, tzinfo=timezone.utc),
                    initial_capital=100.0,
                    allocation_mode='regime',
                )

        self.assertEqual(seen_capitals, [('AAA', 80.0), ('BBB', 20.0)])


def _fake_simulator(metrics):
    class _Sim:
        def run(self):
            return metrics

    return _Sim()
