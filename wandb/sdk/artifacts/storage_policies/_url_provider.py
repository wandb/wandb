"""Thread-safe URL provider for multipart downloads with TTL-based caching."""

from __future__ import annotations

import threading
import time
from typing import Callable


class SharedUrlProvider:
    """Thread-safe URL provider with TTL-based caching.

    When multiple threads need to refresh an expired URL, this class ensures
    that recently-fetched URLs are reused rather than making redundant API calls.

    Design choices:
    - TTL (time-to-live): How long a fetched URL is considered "fresh enough" to reuse.
      Default 5 seconds - if a URL was fetched within the last 5 seconds, reuse it.
    - No strict single-flight: Multiple threads MAY fetch concurrently during the
      refresh window, but only the most recent result is kept. This is simpler than
      full single-flight coordination and sufficient for our use case.
    - Thread-safe via lock: All state mutations are protected by a lock.
    """

    def __init__(self, fetch_fn: Callable[[], str], ttl_seconds: float = 5.0):
        """Initialize the provider.

        Args:
            fetch_fn: Callable that fetches a fresh URL (e.g., GraphQL API call).
                     This function should be idempotent and thread-safe.
            ttl_seconds: How long a fetched URL is considered fresh. Threads that
                        need a URL within this window will reuse the cached one.
        """
        self._fetch_fn = fetch_fn
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._url: str | None = None
        self._fetched_at: float = 0  # monotonic timestamp

    def get_url(self) -> str:
        """Get the current URL, fetching a fresh one if needed.

        Returns:
            The URL to use for download. May be cached if recently fetched.
        """
        now = time.monotonic()

        # Fast path: check if cached URL is still fresh
        with self._lock:
            if self._url and (now - self._fetched_at) < self._ttl:
                return self._url

        # Slow path: fetch a fresh URL
        # Note: Multiple threads may reach here simultaneously during the refresh
        # window. This is acceptable - we just use whichever fetch completes last.
        url = self._fetch_fn()
        fetch_time = time.monotonic()

        with self._lock:
            # Only update if our fetch is more recent than what's cached
            if fetch_time > self._fetched_at:
                self._url = url
                self._fetched_at = fetch_time
            return self._url or url

    def invalidate(self) -> None:
        """Mark the cached URL as invalid, forcing next get_url() to fetch fresh.

        Call this when a download fails with 401/403, indicating URL expiration.
        """
        with self._lock:
            self._fetched_at = 0  # Force refresh on next get_url()

    def set_initial_url(self, url: str) -> None:
        """Set the initial URL (e.g., from batch-fetched URLs).

        Args:
            url: The presigned URL fetched during artifact download initialization.
        """
        with self._lock:
            if not self._url:  # Only set if not already set
                self._url = url
                self._fetched_at = time.monotonic()
