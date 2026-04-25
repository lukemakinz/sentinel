from decimal import Decimal
from datetime import timezone
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings

from ingester.models import AggTrade, WhaleCVD, RetailCVD, WhaleThreshold
from ingester.binance_ws import BinanceWebSocketClient

AGGTRADE_BUY = {
    's': 'BTCUSDT',
    'T': 1672531200000,  # 2023-01-01 00:00:00 UTC
    'p': '30000.00',
    'q': '1.00000000',
    'm': False,  # buyer is taker → BUY → positive delta
}

AGGTRADE_SELL = {
    's': 'BTCUSDT',
    'T': 1672531200000,
    'p': '30000.00',
    'q': '1.00000000',
    'm': True,  # buyer is maker → seller is taker → SELL → negative delta
}

AGGTRADE_SMALL = {
    's': 'BTCUSDT',
    'T': 1672531200000,
    'p': '30000.00',
    'q': '0.00500000',  # usd_value = 150 → below whale threshold
    'm': False,
}


@override_settings(TRADING_PAIRS=['BTCUSDT', 'ETHUSDT'])
class AggTradeHandlerTest(TestCase):
    def setUp(self):
        self.client = BinanceWebSocketClient.__new__(BinanceWebSocketClient)
        self.client.pairs = ['btcusdt', 'ethusdt']
        WhaleThreshold.objects.create(symbol='BTCUSDT', threshold_usd=Decimal('10000.00'))

    def test_creates_aggtrade_record(self):
        self.client._process_aggtrade(AGGTRADE_BUY)

        trade = AggTrade.objects.get(symbol='BTCUSDT')
        self.assertEqual(trade.price, Decimal('30000.00'))
        self.assertEqual(trade.quantity, Decimal('1.00000000'))
        self.assertFalse(trade.is_buyer_maker)

    def test_usd_value_is_price_times_quantity(self):
        data = {**AGGTRADE_BUY, 'p': '25000.50', 'q': '0.40000000'}
        self.client._process_aggtrade(data)

        trade = AggTrade.objects.get(symbol='BTCUSDT')
        self.assertAlmostEqual(float(trade.usd_value), 10000.20, places=1)

    def test_buy_creates_positive_whale_cvd(self):
        # 30000 * 1.0 = 30000 >= threshold 10000 → Whale, m=False → BUY → positive
        self.client._process_aggtrade(AGGTRADE_BUY)

        cvd = WhaleCVD.objects.filter(symbol='BTCUSDT').latest('timestamp')
        self.assertGreater(cvd.cumulative_delta, 0)

    def test_sell_creates_negative_whale_cvd(self):
        # 30000 * 1.0 = 30000 >= threshold 10000 → Whale, m=True → SELL → negative
        self.client._process_aggtrade(AGGTRADE_SELL)

        cvd = WhaleCVD.objects.filter(symbol='BTCUSDT').latest('timestamp')
        self.assertLess(cvd.cumulative_delta, 0)

    def test_small_trade_updates_retail_cvd_not_whale(self):
        # 30000 * 0.005 = 150 < threshold 10000 → Retail
        self.client._process_aggtrade(AGGTRADE_SMALL)

        self.assertEqual(WhaleCVD.objects.filter(symbol='BTCUSDT').count(), 0)
        self.assertEqual(RetailCVD.objects.filter(symbol='BTCUSDT').count(), 1)

    def test_whale_cvd_accumulates_across_trades(self):
        buy = {**AGGTRADE_BUY, 'T': 1672531200000}   # +30000
        sell = {**AGGTRADE_SELL, 'T': 1672531260000}  # -30000, 1 minute later

        self.client._process_aggtrade(buy)
        self.client._process_aggtrade(sell)

        cvds = list(WhaleCVD.objects.filter(symbol='BTCUSDT').order_by('timestamp'))
        self.assertEqual(float(cvds[0].cumulative_delta), 30000.0)
        self.assertEqual(float(cvds[1].cumulative_delta), 0.0)

    def test_no_whale_threshold_uses_default(self):
        # No threshold for ETHUSDT → should use default $10,000
        data = {
            's': 'ETHUSDT',
            'T': 1672531200000,
            'p': '2000.00',
            'q': '10.00000000',  # usd_value = 20000 > default 10000 → Whale
            'm': False,
        }
        self.client._process_aggtrade(data)

        self.assertEqual(WhaleCVD.objects.filter(symbol='ETHUSDT').count(), 1)
        self.assertEqual(RetailCVD.objects.filter(symbol='ETHUSDT').count(), 0)

    def test_stream_url_includes_aggtrade_streams(self):
        client = BinanceWebSocketClient.__new__(BinanceWebSocketClient)
        client.pairs = ['btcusdt', 'ethusdt']
        client.base_url = 'wss://fstream.binance.com'
        url = client._build_stream_url()
        self.assertIn('btcusdt@aggTrade', url)
        self.assertIn('ethusdt@aggTrade', url)

    def test_process_message_routes_aggtrade(self):
        with patch.object(self.client, '_handle_aggtrade') as mock_handler:
            import asyncio
            data = {'stream': 'btcusdt@aggTrade', 'data': AGGTRADE_BUY}
            asyncio.get_event_loop().run_until_complete(self.client._process_message(data))
            mock_handler.assert_called_once_with(AGGTRADE_BUY)
