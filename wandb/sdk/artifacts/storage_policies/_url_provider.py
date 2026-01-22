"""Thread-safe URL provider for multipart downloads with on-demand refresh."""

from __future__ import annotations

import threading
import time
from typing import Callable


class SharedUrlProvider:
    """Thread-safe URL provider with on-demand refresh.

    When multiple threads need to refresh an expired URL, this class ensures
    that recently-fetched URLs are reused rather than making redundant API calls.

    Design choices:
    - On-demand refresh: URLs are only refreshed when explicitly invalidated
      (e.g., after a 401/403 error), not proactively based on TTL.
    - TTL for deduplication: When invalidated, multiple threads may try to refresh
      simultaneously. The TTL prevents redundant fetches by reusing a URL that was
      just fetched by another thread.
    - Thread-safe via lock: All state mutations are protected by a lock.
    """

    def __init__(self, fetch_fn: Callable[[], str], ttl_seconds: float = 5.0):
        """Initialize the provider.

        Args:
            fetch_fn: Callable that fetches a fresh URL (e.g., GraphQL API call).
                     This function should be idempotent and thread-safe.
            ttl_seconds: After invalidation, how long to reuse a freshly-fetched URL
                        before allowing another fetch. This prevents redundant API
                        calls when multiple threads hit 401/403 simultaneously.
        """
        self._fetch_fn = fetch_fn
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._url: str | None = None
        self._fetched_at: float = 0  # monotonic timestamp
        self._invalidated: bool = False

    def get_url(self) -> str:
        """Get the current URL, fetching a fresh one only if invalidated.

        Returns:
            The URL to use for download.
        """
        now = time.monotonic()

        with self._lock:
            # If we have a valid URL and it hasn't been invalidated, return it
            if self._url and not self._invalidated:
                return self._url

            # If invalidated but another thread just fetched, reuse that
            if self._url and self._invalidated and (now - self._fetched_at) < self._ttl:
                return self._url

            # Need to fetch - mark that we're about to fetch
            needs_fetch = True

        if needs_fetch:
            # Fetch outside the lock to avoid blocking other threads
            url = self._fetch_fn()
            fetch_time = time.monotonic()

            with self._lock:
                # Only update if our fetch is more recent than what's cached
                if fetch_time > self._fetched_at:
                    self._url = url
                    self._fetched_at = fetch_time
                    self._invalidated = False
                return self._url or url

        # Should not reach here, but satisfy type checker
        with self._lock:
            return self._url or ""

    def invalidate(self) -> None:
        """Mark the cached URL as invalid, forcing next get_url() to fetch fresh.

        Call this when a download fails with 401/403, indicating URL expiration.
        """
        with self._lock:
            self._invalidated = True
            # Reset fetched_at so TTL check fails until a new URL is fetched
            self._fetched_at = 0

    def set_initial_url(self, url: str) -> None:
        """Set the initial URL (e.g., from batch-fetched URLs).

        Args:
            url: The presigned URL fetched during artifact download initialization.
        """
        with self._lock:
            if not self._url:  # Only set if not already set
                self._url = url
                self._fetched_at = time.monotonic()
                self._invalidated = False
