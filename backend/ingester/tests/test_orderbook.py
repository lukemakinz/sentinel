import asyncio
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings

from ingester.binance_ws import BinanceWebSocketClient
from ingester.models import OrderBookSnapshot
from ingester.orderbook import summarize_depth


DEPTH = {
    'E': 1_700_000_000_000,
    'T': 1_700_000_000_000,
    's': 'BTCUSDT',
    'u': 12345,
    'b': [['100.0', '2.0'], ['99.5', '3.0']],
    'a': [['100.5', '1.0'], ['101.0', '2.0']],
}


class OrderBookFeatureTest(TestCase):
    def test_summary_computes_spread_depth_and_imbalance(self):
        result = summarize_depth(DEPTH['b'], DEPTH['a'])

        self.assertEqual(result['best_bid'], Decimal('100.0'))
        self.assertEqual(result['best_ask'], Decimal('100.5'))
        self.assertGreater(result['bid_depth_20_usd'], 0)
        self.assertGreater(result['ask_depth_20_usd'], 0)
        self.assertGreater(result['imbalance_20'], 0)
        self.assertAlmostEqual(float(result['spread_bps']), 49.8753, places=3)

    def test_crossed_or_empty_book_is_rejected(self):
        self.assertIsNone(summarize_depth([], DEPTH['a']))
        self.assertIsNone(summarize_depth([['101', '1']], [['100', '1']]))

    @override_settings(
        TRADING_PAIRS=['SOLUSDT'],
        GLOBAL_CONTEXT_PAIRS=['BTCUSDT', 'ETHUSDT'],
    )
    def test_context_pairs_are_collected_even_outside_trade_watchlist(self):
        client = BinanceWebSocketClient()

        self.assertEqual(client.pairs, ['btcusdt', 'ethusdt', 'solusdt'])
        self.assertEqual(client.trade_pairs, ['solusdt'])

        urls = client._build_stream_urls()
        self.assertNotIn('btcusdt@aggTrade', urls['market'])
        self.assertNotIn('ethusdt@depth20', urls['public'])
        self.assertIn('solusdt@aggTrade', urls['market'])
        self.assertIn('solusdt@depth20@500ms', urls['public'])


@override_settings(
    TRADING_PAIRS=['BTCUSDT'],
    ORDER_BOOK_STREAM_ENABLED=True,
    ORDER_BOOK_SNAPSHOT_INTERVAL_SECONDS=5,
)
class OrderBookIngestionTest(TestCase):
    def setUp(self):
        self.client = BinanceWebSocketClient.__new__(BinanceWebSocketClient)
        self.client.pairs = ['btcusdt']
        self.client.base_url = 'wss://fstream.binance.com'
        self.client._last_depth_persisted = {}

    def test_stream_urls_separate_market_and_public_routes(self):
        urls = self.client._build_stream_urls()

        self.assertIn('/market/stream?', urls['market'])
        self.assertIn('btcusdt@aggTrade', urls['market'])
        self.assertNotIn('@depth20', urls['market'])
        self.assertIn('/public/stream?', urls['public'])
        self.assertIn('btcusdt@depth20@500ms', urls['public'])
        self.assertNotIn('@aggTrade', urls['public'])

    def test_depth_event_is_persisted_and_downsampled(self):
        first = self.client._process_depth(DEPTH)
        second = self.client._process_depth({**DEPTH, 'E': DEPTH['E'] + 1_000, 'u': 12346})
        third = self.client._process_depth({**DEPTH, 'E': DEPTH['E'] + 5_000, 'u': 12347})

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertIsNotNone(third)
        self.assertEqual(OrderBookSnapshot.objects.count(), 2)
        snapshot = OrderBookSnapshot.objects.order_by('-timestamp').first()
        self.assertEqual(snapshot.last_update_id, 12347)
        self.assertGreater(snapshot.imbalance_20, 0)

    def test_process_message_routes_depth(self):
        with patch.object(self.client, '_handle_depth') as handler:
            asyncio.get_event_loop().run_until_complete(self.client._process_message({
                'stream': 'btcusdt@depth20@250ms',
                'data': DEPTH,
            }))
            handler.assert_called_once_with(DEPTH)


@override_settings(
    TRADING_PAIRS=['SOLUSDT'],
    GLOBAL_CONTEXT_PAIRS=['BTCUSDT', 'ETHUSDT'],
    BREADTH_PAIRS=['SOLUSDT', 'XRPUSDT', 'DOGEUSDT'],
    BREADTH_INTERVALS=['15m', '1h', '4h'],
)
class BreadthPairIngestionTest(TestCase):
    def test_breadth_pairs_get_context_klines_only(self):
        client = BinanceWebSocketClient()

        # SOL is already a trade pair, so it is not duplicated as breadth-only.
        self.assertEqual(client.breadth_pairs, ['xrpusdt', 'dogeusdt'])
        urls = client._build_stream_urls()
        for interval in ('15m', '1h', '4h'):
            self.assertIn(f'xrpusdt@kline_{interval}', urls['market'])
        self.assertNotIn('xrpusdt@kline_1m', urls['market'])
        self.assertNotIn('xrpusdt@aggTrade', urls['market'])
        self.assertNotIn('xrpusdt@markPrice', urls['market'])
        self.assertNotIn('xrpusdt@depth20', urls.get('public', ''))
        self.assertEqual(client.trade_pairs, ['solusdt'])

    def test_breadth_pairs_persist_closed_candles_only(self):
        from asgiref.sync import async_to_sync

        from ingester.models import Candle

        client = BinanceWebSocketClient()

        def kline(symbol, closed):
            return {'k': {
                't': 1_760_000_000_000, 's': symbol, 'i': '1h', 'o': '1', 'h': '2',
                'l': '0.5', 'c': '1.5', 'v': '10', 'q': '15', 'V': '5', 'Q': '7',
                'n': 3, 'x': closed,
            }}

        async_to_sync(client._handle_kline)(kline('XRPUSDT', False))
        self.assertFalse(Candle.objects.filter(symbol='XRPUSDT').exists())
        async_to_sync(client._handle_kline)(kline('XRPUSDT', True))
        self.assertTrue(Candle.objects.filter(symbol='XRPUSDT', is_closed=True).exists())
        # Evaluated instruments keep live (unclosed) updates.
        async_to_sync(client._handle_kline)(kline('SOLUSDT', False))
        self.assertTrue(Candle.objects.filter(symbol='SOLUSDT', is_closed=False).exists())
