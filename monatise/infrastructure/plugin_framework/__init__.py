"""Monatise plugin framework."""

from monatise.infrastructure.plugin_framework.manager import PluginManager
from monatise.infrastructure.plugin_framework.models import (
    PluginCapability,
    PluginContext,
    PluginDependency,
    PluginError,
    PluginLifecycle,
    PluginManifest,
    PluginRegistration,
    PluginState,
)

__all__ = [
    "PluginCapability",
    "PluginContext",
    "PluginDependency",
    "PluginError",
    "PluginLifecycle",
    "PluginManager",
    "PluginManifest",
    "PluginRegistration",
    "PluginState",
]
