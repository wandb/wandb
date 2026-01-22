"""Helpers and constants for multipart upload and download."""

from __future__ import annotations

import logging
import math
import random
import threading
import time
from concurrent.futures import FIRST_EXCEPTION, Executor, wait
from dataclasses import dataclass, field
from queue import Queue
from typing import TYPE_CHECKING, Any, Final, Iterator, Union

import requests
from typing_extensions import TypeAlias, TypeIs, final

from wandb import env
from wandb.sdk.artifacts.artifact_file_cache import Opener

if TYPE_CHECKING:
    from requests import Session

    from ._url_provider import SharedUrlProvider

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
    q: Queue[QueuedChunk]
    cancel: threading.Event = field(default_factory=threading.Event)


def multipart_download(
    executor: Executor,
    session: Session,
    url: str,
    size: int,
    cached_open: Opener,
    url_provider: SharedUrlProvider,
    part_size: int = MULTI_DEFAULT_PART_SIZE,
):
    """Download file as multiple parts in parallel.

    Only one thread for writing to file. Each part run one http request in one thread.
    HTTP response chunk of a file part is sent to the writer thread via a queue.

    Args:
        executor: Thread pool executor for parallel downloads.
        session: HTTP session for making requests.
        url: Initial presigned URL for downloading the file.
        size: Total file size in bytes.
        cached_open: Opener function for writing to cache.
        url_provider: SharedUrlProvider for refreshing expired URLs.
                     Chunks will retry with fresh URLs on 401/403.
        part_size: Size of each download part in bytes.
    """
    # ------------------------------------------------------------------------------
    # Shared between threads
    ctx = MultipartDownloadContext(q=Queue(maxsize=500))

    # Set initial URL in provider
    url_provider.set_initial_url(url)

    # Put cache_open at top so we remove the tmp file when there is network error.
    with cached_open("wb") as f:

        def download_chunk(start: int, end: int | None = None) -> None:
            # Error from another thread, no need to start
            if ctx.cancel.is_set():
                return

            # https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Range
            # Start and end are both inclusive. An empty end uses the actual end
            # of the file. Example string: "bytes=0-499".
            bytes_range = f"{start}-" if (end is None) else f"{start}-{end}"
            headers = {"Range": f"bytes={bytes_range}"}

            # Get URL from provider (may be refreshed if expired)
            current_url = url_provider.get_url()

            # FIXME: Sleep for 2 minutes to simulate URL expiration
            # print("Sleeping for 70s to simulate URL expiration")
            # time.sleep(70)
            # print("Done sleeping")

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    with session.get(
                        url=current_url, headers=headers, stream=True
                    ) as rsp:
                        rsp.raise_for_status()

                        offset = start
                        for chunk in rsp.iter_content(chunk_size=RSP_CHUNK_SIZE):
                            if ctx.cancel.is_set():
                                return
                            ctx.q.put(ChunkContent(offset=offset, data=chunk))
                            offset += len(chunk)
                        return  # Success, exit retry loop

                except requests.HTTPError as e:
                    status_code = getattr(e.response, "status_code", None)
                    if status_code in (401, 403) and attempt < max_retries - 1:
                        # URL likely expired, invalidate and get fresh URL
                        if env.is_debug():
                            logger.debug(
                                f"Download got {status_code} on attempt {attempt + 1}, refreshing URL"
                            )
                        url_provider.invalidate()

                        # Exponential backoff with jitter before retry
                        base_delay = 0.5  # 500ms base
                        max_jitter = 0.5  # up to 500ms jitter
                        delay = base_delay * (2**attempt) + random.uniform(
                            0, max_jitter
                        )
                        time.sleep(delay)

                        current_url = url_provider.get_url()
                        continue  # Retry with new URL
                    raise  # Re-raise if not retryable or max retries exceeded

        def write_chunks() -> None:
            # If all chunks are written or there's an error in another thread, shutdown
            while not (ctx.cancel.is_set() or is_end_chunk(chunk := ctx.q.get())):
                try:
                    # NOTE: Seek works without pre allocating the file on disk.
                    # It automatically creates a sparse file, e.g. ls -hl would show
                    # a bigger size compared to du -sh * because downloading different
                    # chunks is not a sequential write.
                    # See https://man7.org/linux/man-pages/man2/lseek.2.html
                    f.seek(chunk.offset)
                    f.write(chunk.data)

                except Exception as e:
                    if env.is_debug():
                        logger.debug(f"Error writing chunk to file: {e}")
                    ctx.cancel.set()
                    raise

        # Start writer thread first.
        write_future = executor.submit(write_chunks)

        # Start download threads for each chunk.
        download_futures = set()
        for start in range(0, size, part_size):
            # https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Range
            # Start and end are both inclusive. An empty end uses the actual end
            # of the file. Example string: "bytes=0-499".
            end = end if (end := (start + part_size - 1)) < size else None
            download_futures.add(executor.submit(download_chunk, start=start, end=end))

        # Wait for download
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
