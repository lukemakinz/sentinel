"""Discovered strategy plugins.

One module equals one versioned strategy.  New modules are discovered without
editing the engine; operational enable/disable is controlled by settings.
"""
from l2_agents.strategy_engine import discover_strategy_plugins


strategy_registry = discover_strategy_plugins(__name__)


__all__ = ['strategy_registry']
