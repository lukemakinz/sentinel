"""Slippage model — pure math."""
from django.test import TestCase
from backtest.slippage_model import apply_slippage, compute_fee, OrderType


class SlippageTest(TestCase):
    def test_market_order_long_increases_entry(self):
        # Market buy: pay slippage (entry higher)
        price = apply_slippage(100.0, OrderType.MARKET, 'LONG')
        self.assertGreater(price, 100.0)

    def test_market_order_short_decreases_entry(self):
        # Market sell short: entry lower
        price = apply_slippage(100.0, OrderType.MARKET, 'SHORT')
        self.assertLess(price, 100.0)

    def test_limit_order_no_slippage(self):
        # Limit orders fill at exact price
        price = apply_slippage(100.0, OrderType.LIMIT, 'LONG')
        self.assertAlmostEqual(price, 100.0)

    def test_market_slippage_is_01pct(self):
        price = apply_slippage(1000.0, OrderType.MARKET, 'LONG')
        self.assertAlmostEqual(price, 1001.0, places=1)  # 0.1%


class FeeTest(TestCase):
    def test_market_taker_fee_is_005pct(self):
        fee = compute_fee(10000.0, OrderType.MARKET)
        self.assertAlmostEqual(fee, 5.0, places=1)  # 0.05%

    def test_limit_maker_fee_is_002pct(self):
        fee = compute_fee(10000.0, OrderType.LIMIT)
        self.assertAlmostEqual(fee, 2.0, places=1)  # 0.02%

    def test_fee_zero_on_zero_size(self):
        self.assertEqual(compute_fee(0.0, OrderType.MARKET), 0.0)
