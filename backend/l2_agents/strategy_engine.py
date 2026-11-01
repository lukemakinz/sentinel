"""Stable plugin contract for Sentinel setup strategies.

Strategies own setup-specific detection, zone compatibility and entry trigger
rules.  The surrounding engine continues to own data quality, risk, costs,
position management, replay and execution locks.

The distinction between *registered* and *enabled* is intentional.  Disabling
a strategy stops new plans without making historical/open plans impossible to
resolve.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from importlib import import_module
from pkgutil import iter_modules
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from django.conf import settings


STRATEGY_ID_PATTERN = re.compile(r'^[A-Z][A-Z0-9_]{2,63}$')
VALID_STATUSES = frozenset({'RESEARCH_ONLY', 'SHADOW_ONLY', 'PAPER_ELIGIBLE'})


class StrategyConfigurationError(ValueError):
    """A plugin or enabled-strategy setting violates the engine contract."""


class UnknownStrategyError(StrategyConfigurationError):
    """A plan references a strategy plugin that is not installed."""


@dataclass(frozen=True)
class StrategySpec:
    """Versioned metadata consumed by validation, UI and replay."""

    strategy_id: str
    version: str
    display_name: str
    family: str
    status: str
    required_timeframes: tuple[str, ...]
    compatible_management_policies: tuple[str, ...]
    long_zone_kinds: tuple[str, ...]
    short_zone_kinds: tuple[str, ...]
    default_ttl_minutes: int = 60
    max_ttl_minutes: int = 240
    detector_mode: str = 'AI_ADJUDICATED'
    description: str = ''

    def __post_init__(self) -> None:
        if not STRATEGY_ID_PATTERN.fullmatch(self.strategy_id):
            raise StrategyConfigurationError(
                f'Invalid strategy_id {self.strategy_id!r}; use uppercase snake case.',
            )
        if not self.version.strip() or not self.display_name.strip():
            raise StrategyConfigurationError('Strategy version and display name are required.')
        if self.status not in VALID_STATUSES:
            raise StrategyConfigurationError(f'Unsupported strategy status: {self.status}')
        if self.detector_mode not in {'MECHANICAL', 'AI_ADJUDICATED'}:
            raise StrategyConfigurationError(
                f'Unsupported detector mode: {self.detector_mode}',
            )
        if not 0 < self.default_ttl_minutes <= self.max_ttl_minutes <= 240:
            raise StrategyConfigurationError('Strategy TTL must satisfy 0 < default <= max <= 240.')
        if not self.required_timeframes:
            raise StrategyConfigurationError('At least one required timeframe is required.')
        if not self.compatible_management_policies:
            raise StrategyConfigurationError('At least one management policy is required.')
        if not self.long_zone_kinds or not self.short_zone_kinds:
            raise StrategyConfigurationError('Both LONG and SHORT zone contracts are required.')

    def public_contract(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StrategyCandidate:
    """Setup intent produced by a plugin before risk/AI adjudication."""

    strategy_id: str
    direction: str
    entry_zone: tuple[float, float]
    trigger_conditions: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    thesis: tuple[str, ...]
    ttl_minutes: int
    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({}),
    )

    def __post_init__(self) -> None:
        if self.direction not in {'LONG', 'SHORT'}:
            raise StrategyConfigurationError('Candidate direction must be LONG or SHORT.')
        if len(self.entry_zone) != 2:
            raise StrategyConfigurationError('Candidate entry_zone must contain two prices.')
        low, high = (float(value) for value in self.entry_zone)
        if low <= 0 or high <= 0 or low > high:
            raise StrategyConfigurationError(
                'Candidate entry_zone must be positive and sorted low-to-high.',
            )
        if not self.trigger_conditions or not self.invalidation_conditions:
            raise StrategyConfigurationError('Candidate requires trigger and invalidation rules.')
        if self.ttl_minutes <= 0:
            raise StrategyConfigurationError('Candidate TTL must be positive.')


@dataclass(frozen=True)
class StrategyScan:
    candidates: tuple[StrategyCandidate, ...] = ()
    diagnostics: tuple[str, ...] = ()


class StrategyPlugin(ABC):
    """Extension point implemented by every strategy module."""

    spec: StrategySpec

    def scan(self, snapshot: dict) -> StrategyScan:
        """Return causal candidates; AI-only strategies may return none."""
        return StrategyScan(diagnostics=(
            f'{self.spec.strategy_id} has no mechanical detector.',
        ))

    def validate_arm_zone(self, *, direction: str, zone_kind: str) -> None:
        allowed = (
            self.spec.long_zone_kinds
            if direction == 'LONG'
            else self.spec.short_zone_kinds
        )
        if zone_kind not in allowed:
            kinds = ' or '.join(allowed)
            raise ValueError(
                f'{self.spec.display_name} requires a supplied {kinds} zone '
                f'for {direction}.',
            )

    @abstractmethod
    def triggered(self, plan: Any, candle: Mapping[str, Any]) -> bool:
        """Evaluate a closed candle without DB or future-data access."""


class StrategyRegistry:
    """Mutable at application start, read-only during decision processing."""

    def __init__(self, plugins: Iterable[StrategyPlugin] = ()) -> None:
        self._plugins: dict[str, StrategyPlugin] = {}
        for plugin in plugins:
            self.register(plugin)

    def register(self, plugin: StrategyPlugin, *, replace: bool = False) -> None:
        strategy_id = plugin.spec.strategy_id
        if strategy_id in self._plugins and not replace:
            raise StrategyConfigurationError(f'Duplicate strategy_id: {strategy_id}')
        self._plugins[strategy_id] = plugin

    def unregister(self, strategy_id: str) -> StrategyPlugin:
        try:
            return self._plugins.pop(strategy_id)
        except KeyError as exc:
            raise UnknownStrategyError(strategy_id) from exc

    def get(self, strategy_id: str) -> StrategyPlugin:
        try:
            return self._plugins[strategy_id]
        except KeyError as exc:
            raise UnknownStrategyError(strategy_id) from exc

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._plugins))

    def enabled_ids(self) -> tuple[str, ...]:
        configured = getattr(settings, 'AUCTION_ENABLED_STRATEGIES', None)
        if configured is None:
            return self.ids()
        if isinstance(configured, str):
            requested = tuple(
                item.strip() for item in configured.split(',') if item.strip()
            )
        else:
            requested = tuple(str(item).strip() for item in configured if str(item).strip())
        unknown = sorted(set(requested) - set(self._plugins))
        if unknown:
            raise StrategyConfigurationError(
                f'AUCTION_ENABLED_STRATEGIES contains unknown IDs: {", ".join(unknown)}',
            )
        # Preserve deterministic registry order, not environment-string order.
        requested_set = set(requested)
        return tuple(item for item in self.ids() if item in requested_set)

    def status_map(self, *, enabled_only: bool = True) -> dict[str, str]:
        ids = self.enabled_ids() if enabled_only else self.ids()
        return {strategy_id: self.get(strategy_id).spec.status for strategy_id in ids}

    def catalog(self, *, enabled_only: bool = True) -> dict[str, dict[str, Any]]:
        ids = self.enabled_ids() if enabled_only else self.ids()
        return {
            strategy_id: self.get(strategy_id).spec.public_contract()
            for strategy_id in ids
        }

    def scan(self, snapshot: dict, *, strategy_ids: Iterable[str] | None = None) -> StrategyScan:
        selected = tuple(strategy_ids) if strategy_ids is not None else self.enabled_ids()
        candidates: list[StrategyCandidate] = []
        diagnostics: list[str] = []
        for strategy_id in selected:
            plugin = self.get(strategy_id)
            result = plugin.scan(snapshot)
            for candidate in result.candidates:
                if candidate.strategy_id != strategy_id:
                    raise StrategyConfigurationError(
                        f'{strategy_id} emitted candidate for {candidate.strategy_id}.',
                    )
                if candidate.ttl_minutes > plugin.spec.max_ttl_minutes:
                    raise StrategyConfigurationError(
                        f'{strategy_id} candidate exceeds plugin max TTL.',
                    )
            candidates.extend(result.candidates)
            diagnostics.extend(result.diagnostics)
        return StrategyScan(tuple(candidates), tuple(diagnostics))


def discover_strategy_plugins(package_name: str) -> StrategyRegistry:
    """Load every non-private module exporting ``STRATEGY_PLUGIN``.

    Adding a strategy is therefore additive: drop one module into the strategy
    package.  Disabling is configuration-only and preserves historical replay.
    """
    package = import_module(package_name)
    registry = StrategyRegistry()
    module_names = sorted(
        info.name for info in iter_modules(package.__path__)
        if not info.name.startswith('_')
    )
    for module_name in module_names:
        module = import_module(f'{package_name}.{module_name}')
        plugin = getattr(module, 'STRATEGY_PLUGIN', None)
        if plugin is None:
            raise StrategyConfigurationError(
                f'{package_name}.{module_name} must export STRATEGY_PLUGIN.',
            )
        registry.register(plugin)
    return registry
