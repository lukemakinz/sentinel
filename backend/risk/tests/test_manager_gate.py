from unittest.mock import patch

from django.test import TestCase, override_settings

from executor.models import Position
from risk.manager import RiskManager
from risk.trading_state import escalate

BETAS = {'SOLUSDT': {'beta': 1.2, 'source': 'test'}, 'ETHUSDT': {'beta': 1.1, 'source': 'test'}}


@override_settings(INITIAL_BALANCE=250, MAX_RISK_PER_TRADE=0.002, MAX_LEVERAGE=5)
@patch('risk.manager.check_kill_switches', return_value=(True, 'ok'))
@patch('risk.manager.get_position_size_multiplier', return_value=1.0)
@patch('risk.manager.get_atr_for_symbol', return_value=1.0)
@patch('risk.exposure.estimate_betas', side_effect=lambda symbols, days=30: BETAS)
class RiskManagerGateTests(TestCase):
    def test_close_only_rejects_before_any_sizing(self, *_):
        escalate('CLOSE_ONLY', 'feed')
        approved, result = RiskManager().evaluate_trade('SOLUSDT', 'LONG', 'HIGH_CONVICTION', 100.0)
        self.assertFalse(approved)
        self.assertIn('CLOSE_ONLY', result['reason'])

    def test_caution_halves_risk_and_reports_exposure(self, *_):
        _, normal = RiskManager().evaluate_trade('SOLUSDT', 'LONG', 'HIGH_CONVICTION', 100.0)
        escalate('CAUTION', 'vol')
        _, caution = RiskManager().evaluate_trade('SOLUSDT', 'LONG', 'HIGH_CONVICTION', 100.0)
        self.assertAlmostEqual(caution['risk_percent'], normal['risk_percent'] / 2)
        self.assertEqual(caution['trading_state'], 'CAUTION')
        self.assertIn('open_risk_pct', caution['exposure_after'])

    @override_settings(PORTFOLIO_MAX_OPEN_RISK_PCT=0.5)
    def test_existing_book_risk_blocks_new_entry(self, *_):
        Position.objects.create(symbol='ETHUSDT', side='LONG', entry_price=100, quantity=1.5,
                                remaining_quantity=1.5, position_size_usd=150, stop_loss=99.2)
        approved, result = RiskManager().evaluate_trade('SOLUSDT', 'LONG', 'HIGH_CONVICTION', 100.0)
        self.assertFalse(approved)
        self.assertIn('open risk', result['reason'])
