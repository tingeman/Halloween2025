"""
Base classes and helpers for dashboard plugins.

Provides:
- SafeCache: thread-safe thin wrapper around the shared cache object.
- BasePlugin: small base class that normalizes service binding and exposes
  convenience helpers (cache_get/set, mqtt_publish/subscribe).
Plugins should subclass BasePlugin and implement `on_register(app, services)`.
"""
from abc import ABC, abstractmethod
import threading
from typing import Any, Dict, Iterator
from collections.abc import MutableMapping


class SafeCache(MutableMapping):
    """A tiny thread-safe, dict-like wrapper around a mapping.

    This implements the MutableMapping protocol so plugins can use the
    familiar dict syntax (e.g. `self.cache[key] = value`) while still
    getting thread-safe access via an internal RLock. The class also
    exposes the legacy helpers `get`, `set`, `pop`, and `as_dict` for
    backward compatibility.

    Notes/caveats:
    - The wrapper acquires the lock for each individual mapping operation.
      If you need to perform a compound read-modify-write atomically,
      consider adding a helper on the host side or using `as_dict()` and
      performing your own locking strategy.
    - The backing mapping may be any dict-like object provided by the
      application (often a simple dict). We copy on `as_dict()` to avoid
      exposing internal state while the lock is released.
    """

    def __init__(self, backing: Dict[str, Any]) -> None:
        self._lock = threading.RLock()
        self._backing = backing

    # MutableMapping interface -------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        with self._lock:
            return self._backing[key]

    def __setitem__(self, key: str, value: Any) -> None:
        with self._lock:
            self._backing[key] = value

    def __delitem__(self, key: str) -> None:
        with self._lock:
            del self._backing[key]

    def __iter__(self) -> Iterator[str]:
        with self._lock:
            # iterate over a snapshot to avoid race conditions
            return iter(list(self._backing.keys()))

    def __len__(self) -> int:
        with self._lock:
            return len(self._backing)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            return key in self._backing

    # Backwards-compatible helpers ---------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._backing.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._backing[key] = value

    def pop(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._backing.pop(key, default)

    def as_dict(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._backing)

    def transaction(self):
        """Return a context manager that yields the backing mapping while
        holding the internal lock.

        Use this when you need to perform a compound read-modify-write
        atomically. Example:

            with self.cache.transaction() as backing:
                backing['counter'] = backing.get('counter', 0) + 1

        The context manager acquires the RLock on enter and releases it on
        exit. The object yielded is the raw backing mapping (not a copy), so
        be careful to keep operations bounded and avoid long-running work
        while holding the lock.
        """

        class _Tx:
            def __init__(self, cache: "SafeCache") -> None:
                self._cache = cache

            def __enter__(self):
                self._cache._lock.acquire()
                return self._cache._backing

            def __exit__(self, exc_type, exc, tb):
                self._cache._lock.release()
                return False

        return _Tx(self)

    def locked(self):
        """Convenience alias for `transaction()` so plugin code can use
        `with self.cache.locked():` which reads nicely in call sites.
        """

        return self.transaction()


class BasePlugin(ABC):
    """
    Base plugin providing safe access to services.

    Plugins should subclass and implement:
      - layout(self) -> dash fragment
      - on_register(self, app, services) -> None

    The loader calls register(app, services) which sets up helpers then calls
    your on_register.
    """

    def register(self, app, services: Dict[str, Any]) -> None:
        """Called by the loader. Binds services to the instance and wraps the cache.
        """
        self._services = services
        # mqtt client or None
        self._mqtt = services.get("mqtt")
        # tick id used by dashboards
        self._tick = services.get("tick_id")
        # wrap the cache in a SafeCache to avoid ad-hoc locking across plugins
        raw_cache = services.get("cache", {})
        if isinstance(raw_cache, SafeCache):
            self._cache = raw_cache
        else:
            self._cache = SafeCache(raw_cache)

        # Expose the cache as a dict-like object so plugins can use either
        # `self.cache[...] = ...` or the legacy helpers below. The underlying
        # SafeCache ensures thread-safe access.
        self.cache = self._cache

        # convenience helpers bound to the instance for backward compatibility
        self.cache_get = self._cache.get
        self.cache_set = self._cache.set
        self.cache_pop = self._cache.pop

        # mqtt helpers - no-ops if mqtt not available
        def _publish(topic, payload, **kwargs):
            if self._mqtt:
                try:
                    return self._mqtt.publish(topic, payload, **kwargs)
                except Exception:
                    # don't let a publishing error break plugin registration
                    return None
            return None

        def _subscribe(topic, cb):
            if self._mqtt:
                try:
                    return self._mqtt.subscribe(topic, cb)
                except Exception:
                    return None
            return None

        self.mqtt_publish = _publish
        self.mqtt_subscribe = _subscribe

        # call subclass hook
        return self.on_register(app, services)

    @abstractmethod
    def on_register(self, app, services: Dict[str, Any]) -> None:
        """Subclass should register callbacks and subscriptions here."""
        raise NotImplementedError
