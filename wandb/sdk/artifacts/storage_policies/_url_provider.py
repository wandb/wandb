"""Thread-safe URL provider for multipart downloads with on-demand refresh."""

from __future__ import annotations

import threading
from typing import Callable


class SharedUrlProvider:
    """Thread-safe URL provider with on-demand refresh.

    URLs are only refreshed when explicitly invalidated (e.g., after a 401/403 error).
    All operations are serialized via a lock for simplicity.
    """

    def __init__(
        self,
        initial_url: str,
        fetch_fn: Callable[[], str],
    ):
        """Initialize the provider.

        Args:
            initial_url: The initial presigned URL (e.g., from batch-fetched URLs).
            fetch_fn: Callable that fetches a fresh URL (e.g., GraphQL API call).
        """
        self._fetch_fn = fetch_fn
        self._lock = threading.Lock()
        self._url: str = initial_url
        self._invalidated: bool = False

    def get_url(self) -> str:
        """Get the current URL, fetching a fresh one only if invalidated."""
        with self._lock:
            if self._invalidated:
                self._url = self._fetch_fn()
                self._invalidated = False
            return self._url

    def invalidate(self) -> None:
        """Mark the cached URL as invalid, forcing next get_url() to fetch fresh."""
        with self._lock:
            self._invalidated = True
