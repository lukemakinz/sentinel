from types import MappingProxyType, SimpleNamespace

from django.test import SimpleTestCase, override_settings

from l2_agents.strategy_engine import (
    StrategyCandidate,
    StrategyConfigurationError,
    StrategyPlugin,
    StrategyRegistry,
    StrategyScan,
    StrategySpec,
)
from l2_agents.strategies import strategy_registry


class ExampleStrategy(StrategyPlugin):
    spec = StrategySpec(
        strategy_id='TEST_PULLBACK',
        version='test-v1',
        display_name='Test pullback',
        family='TREND_CONTINUATION',
        status='SHADOW_ONLY',
        required_timeframes=('1h', '5m'),
        compatible_management_policies=('P0_INITIAL_STOP',),
        long_zone_kinds=('RECENT_SUPPORT',),
        short_zone_kinds=('RECENT_RESISTANCE',),
        default_ttl_minutes=30,
        max_ttl_minutes=60,
        detector_mode='MECHANICAL',
    )

    def scan(self, snapshot):
        return StrategyScan(candidates=(StrategyCandidate(
            strategy_id=self.spec.strategy_id,
            direction='LONG',
            entry_zone=(99.0, 100.0),
            trigger_conditions=('5m bullish close',),
            invalidation_conditions=('5m close below 99',),
            thesis=('1h trend aligned',),
            ttl_minutes=30,
            metadata=MappingProxyType({'source': 'test'}),
        ),))

    def triggered(self, plan, candle):
        return float(candle['close']) > plan.zone_high


class StrategyRegistryTest(SimpleTestCase):
    def test_builtin_plugins_are_discovered_with_versioned_contracts(self):
        self.assertEqual(strategy_registry.ids(), (
            'SAI1_FAILED_AUCTION',
            'SAI1_IFVG_FLIP',
            'SAI1_TREND_RETEST',
        ))
        catalog = strategy_registry.catalog(enabled_only=False)
        self.assertEqual(
            catalog['SAI1_FAILED_AUCTION']['detector_mode'],
            'MECHANICAL',
        )
        self.assertTrue(catalog['SAI1_TREND_RETEST']['version'])

    def test_duplicate_strategy_id_is_rejected(self):
        registry = StrategyRegistry((ExampleStrategy(),))
        with self.assertRaisesRegex(StrategyConfigurationError, 'Duplicate'):
            registry.register(ExampleStrategy())

    @override_settings(AUCTION_ENABLED_STRATEGIES=())
    def test_disable_stops_new_candidates_but_keeps_plugin_for_history(self):
        registry = StrategyRegistry((ExampleStrategy(),))

        self.assertEqual(registry.enabled_ids(), ())
        self.assertEqual(registry.scan({}).candidates, ())
        self.assertEqual(registry.get('TEST_PULLBACK').spec.version, 'test-v1')

    @override_settings(AUCTION_ENABLED_STRATEGIES=('MISSING_STRATEGY',))
    def test_unknown_enabled_id_fails_closed(self):
        registry = StrategyRegistry((ExampleStrategy(),))
        with self.assertRaisesRegex(StrategyConfigurationError, 'unknown IDs'):
            registry.enabled_ids()

    @override_settings(AUCTION_ENABLED_STRATEGIES=('TEST_PULLBACK',))
    def test_scan_and_trigger_are_owned_by_plugin(self):
        registry = StrategyRegistry((ExampleStrategy(),))
        scan = registry.scan({})

        self.assertEqual(scan.candidates[0].strategy_id, 'TEST_PULLBACK')
        plan = SimpleNamespace(zone_high=100.0)
        self.assertTrue(registry.get('TEST_PULLBACK').triggered(
            plan, {'close': 100.1},
        ))

    def test_plugin_zone_contract_is_directional(self):
        plugin = ExampleStrategy()
        plugin.validate_arm_zone(direction='LONG', zone_kind='RECENT_SUPPORT')
        with self.assertRaisesRegex(ValueError, 'RECENT_RESISTANCE'):
            plugin.validate_arm_zone(
                direction='SHORT', zone_kind='RECENT_SUPPORT',
            )

    @override_settings(AUCTION_ENABLED_STRATEGIES=('TEST_PULLBACK',))
    def test_candidate_for_different_strategy_is_rejected(self):
        class BrokenStrategy(ExampleStrategy):
            def scan(self, snapshot):
                candidate = super().scan(snapshot).candidates[0]
                return StrategyScan(candidates=(StrategyCandidate(
                    **{**candidate.__dict__, 'strategy_id': 'OTHER_STRATEGY'},
                ),))

        registry = StrategyRegistry((BrokenStrategy(),))
        with self.assertRaisesRegex(StrategyConfigurationError, 'emitted candidate'):
            registry.scan({})
