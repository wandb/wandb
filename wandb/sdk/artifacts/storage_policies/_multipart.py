"""Helpers and constants for multipart upload and download."""

from __future__ import annotations

import logging
import math
import threading
from concurrent.futures import FIRST_EXCEPTION, Executor, wait
from dataclasses import dataclass, field
from queue import Queue
from typing import IO, TYPE_CHECKING, Any, Callable, Final, Iterator, Union

import requests
from typing_extensions import TypeAlias, TypeIs, final

from wandb import env
from wandb.sdk.artifacts.artifact_file_cache import Opener
from wandb.sdk.lib import retry

if TYPE_CHECKING:
    from requests import Session

logger = logging.getLogger(__name__)

KiB: Final[int] = 1024
MiB: Final[int] = 1024**2
GiB: Final[int] = 1024**3
TiB: Final[int] = 1024**4

# AWS S3 max upload parts without having to make additional requests for extra parts
MAX_PARTS = 1_000
MIN_MULTI_UPLOAD_SIZE = 2 * GiB
MAX_MULTI_UPLOAD_SIZE = 5 * TiB

# Minimum size to switch to multipart download, same threshold as upload.
MIN_MULTI_DOWNLOAD_SIZE = MIN_MULTI_UPLOAD_SIZE

# Multipart download part size matches the upload size and is hard coded to
# 100 MB.
# https://github.com/wandb/wandb/blob/7b2a13cb8efcd553317167b823c8e52d8c3f7c4e/core/pkg/artifacts/saver.go#L496
# https://docs.aws.amazon.com/AmazonS3/latest/userguide/optimizing-performance-guidelines.html#optimizing-performance-guidelines-get-range
MULTI_DEFAULT_PART_SIZE = 100 * MiB

# Chunk size for reading http response and writing to disk.
RSP_CHUNK_SIZE = 1 * MiB


@final
class _ChunkSentinel:
    """Signal the end of the multipart chunk queue.

    Queue consumers terminate when they receive this item from the queue. Do
    not instantiate this class directly; use the `END_CHUNK` constant as a
    pseudo-singleton instead.

    NOTE: Use this only in multi-threaded (not multi-process) contexts because
    it is not guaranteed to be process-safe.
    """

    def __repr__(self) -> str:
        return "ChunkSentinel"


END_CHUNK: Final[_ChunkSentinel] = _ChunkSentinel()


def is_end_chunk(obj: Any) -> TypeIs[_ChunkSentinel]:
    """Returns True if the object is the terminal queue item for multipart downloads."""
    # Needed for type checking, since _ChunkSentinel isn't formally a singleton.
    return obj is END_CHUNK


@dataclass(frozen=True)
class ChunkContent:
    __slots__ = ("offset", "data")  # slots=True only introduced in Python 3.10
    offset: int
    data: bytes


QueuedChunk: TypeAlias = Union[ChunkContent, _ChunkSentinel]


def should_multipart_download(size: int | None, override: bool | None = None) -> bool:
    return ((size or 0) >= MIN_MULTI_DOWNLOAD_SIZE) if (override is None) else override


def calc_part_size(file_size: int, min_part_size: int = MULTI_DEFAULT_PART_SIZE) -> int:
    # Default to a chunk size of 100MiB. S3 has a cap of 10,000 upload parts.
    return max(math.ceil(file_size / MAX_PARTS), min_part_size)


def scan_chunks(path: str, chunk_size: int) -> Iterator[bytes]:
    with open(path, "rb") as f:
        while data := f.read(chunk_size):
            yield data


@dataclass
class MultipartDownloadContext:
    """Shared state for multipart download threads."""

    session: Session
    q: Queue[QueuedChunk]
    cancel: threading.Event = field(default_factory=threading.Event)

    # URL state management (thread-safe)
    _url_lock: threading.Lock = field(default_factory=threading.Lock)
    _url: str = ""
    _url_invalidated: bool = False
    _url_fetch_fn: Callable[[], str] | None = None

    def get_url(self) -> str:
        """Get the current URL, fetching a fresh one only if invalidated."""
        with self._url_lock:
            if self._url_invalidated and self._url_fetch_fn:
                self._url = self._url_fetch_fn()
                self._url_invalidated = False
            return self._url

    def invalidate_url(self) -> None:
        """Mark the cached URL as invalid, forcing next get_url() to fetch fresh."""
        with self._url_lock:
            self._url_invalidated = True


def _download_chunk_with_refresh(
    ctx: MultipartDownloadContext,
    start: int,
    end: int | None,
) -> None:
    """Download a single chunk with refresh logic for expired presigned URLs.

    Args:
        ctx: Shared download context with session, queue, cancel event, and URL state.
        start: Start byte offset (inclusive).
        end: End byte offset (inclusive), or None for end of file.
    """
    if ctx.cancel.is_set():
        return

    # https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Range
    # Start and end are both inclusive. Example: "bytes=0-499".
    bytes_range = f"{start}-" if (end is None) else f"{start}-{end}"
    headers = {"Range": f"bytes={bytes_range}"}

    def check_retry_fn(e: Exception) -> bool:
        """Check if we should retry this exception and refresh URL if needed."""
        if not isinstance(e, requests.HTTPError):
            return False

        # Only retry 401 and 403 because they are from expired presigned url.
        # and not handled by existing retry strategy in make_http_session.
        # Retry logic in make_http_session uses same url and cannot handle
        # expired urls unless caller refresh and uses a new url.
        status_code = getattr(e.response, "status_code", None)
        if status_code in (401, 403):
            # URL likely expired, invalidate so next get_url() fetches fresh
            if env.is_debug():
                logger.debug(f"Download got {status_code}, refreshing URL for retry")
            ctx.invalidate_url()
            return True
        return False

    def attempt_download() -> None:
        with ctx.session.get(url=ctx.get_url(), headers=headers, stream=True) as rsp:
            rsp.raise_for_status()

            offset = start
            for chunk in rsp.iter_content(chunk_size=RSP_CHUNK_SIZE):
                if ctx.cancel.is_set():
                    return
                ctx.q.put(ChunkContent(offset=offset, data=chunk))
                offset += len(chunk)

    # Use common retry logic with exponential backoff
    retrier = retry.Retry(
        attempt_download,
        num_retries=3,
        check_retry_fn=check_retry_fn,
        retryable_exceptions=(requests.HTTPError,),
        error_prefix="Multipart download chunk url expired",
    )
    retrier(retry_sleep_base=0.5)


def _write_chunks(ctx: MultipartDownloadContext, file: IO[bytes]) -> None:
    """Write downloaded chunks to file.

    Args:
        ctx: Shared download context with queue and cancel event.
        file: File handle to write to.
    """
    # Process chunks until cancelled or END_CHUNK sentinel received
    while not (ctx.cancel.is_set() or is_end_chunk(chunk := ctx.q.get())):
        try:
            # NOTE: Seek works without pre-allocating the file on disk.
            # It automatically creates a sparse file, e.g. ls -hl would show
            # a bigger size compared to du -sh * because downloading different
            # chunks is not a sequential write.
            # See https://man7.org/linux/man-pages/man2/lseek.2.html
            file.seek(chunk.offset)
            file.write(chunk.data)
        except Exception as e:
            if env.is_debug():
                logger.debug(f"Error writing chunk to file: {e}")
            ctx.cancel.set()
            raise


def multipart_download(
    executor: Executor,
    session: Session,
    size: int,
    cached_open: Opener,
    initial_url: str,
    fetch_fn: Callable[[], str],
    part_size: int = MULTI_DEFAULT_PART_SIZE,
) -> None:
    """Download file as multiple parts in parallel.

    Uses one thread for writing to file. Each part runs one HTTP request in one thread.
    HTTP response chunks are sent to the writer thread via a queue.

    Args:
        executor: Thread pool executor for parallel downloads.
        session: HTTP session for making requests.
        size: Total file size in bytes.
        cached_open: Opener function for writing to cache.
        initial_url: The initial presigned URL for downloading.
        fetch_fn: Callable that fetches a fresh URL when the current one expires.
        part_size: Size of each download part in bytes.
    """
    ctx = MultipartDownloadContext(
        session=session,
        q=Queue(maxsize=500),
        _url=initial_url,
        _url_fetch_fn=fetch_fn,
    )

    # Put cache_open at top so we remove the tmp file when there is network error.
    with cached_open("wb") as f:
        # Start writer thread first
        write_future = executor.submit(_write_chunks, ctx, f)

        # Start download threads for each chunk
        download_futures = set()
        for start in range(0, size, part_size):
            # https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Range
            # Start and end are both inclusive. None for end uses actual end of file.
            end = end if (end := (start + part_size - 1)) < size else None
            download_futures.add(
                executor.submit(
                    _download_chunk_with_refresh,
                    ctx,
                    start,
                    end,
                )
            )

        # Wait for downloads and handle errors
        done, not_done = wait(download_futures, return_when=FIRST_EXCEPTION)
        try:
            for fut in done:
                fut.result()
        except Exception as e:
            if env.is_debug():
                logger.debug(f"Error downloading file: {e}")
            ctx.cancel.set()

            # Cancel any pending futures.  Note:
            # - `Future.cancel()` does NOT stop the future if it's running, which is why
            #   there's a separate `threading.Event` to ensure cooperative cancellation.
            # - Once Python 3.8 support is dropped, replace these `fut.cancel()`
            #   calls with `Executor.shutdown(cancel_futures=True)`.
            for fut in not_done:
                fut.cancel()
            raise
        finally:
            # Always signal the writer to stop
            ctx.q.put(END_CHUNK)
            write_future.result()
