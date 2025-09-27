"""Thin package wrapper for the plugin_base helpers.

Expose SafeCache and BasePlugin at package-level so the package can be
installed and imported as `plugin_base`.
"""

from .plugin_base import SafeCache, BasePlugin

__all__ = ["SafeCache", "BasePlugin"]
