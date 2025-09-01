"""Helpers and constants for multipart upload and download."""

from __future__ import annotations

import concurrent.futures
import logging
import math
import threading
from dataclasses import dataclass
from queue import Queue
from typing import IO, Any, Final, Iterator

import requests
from typing_extensions import TypeIs

from wandb import env
from wandb.sdk.artifacts.artifact_file_cache import Opener

logger = logging.getLogger(__name__)

KiB: Final[int] = 1024
MiB: Final[int] = 1024**2
GiB: Final[int] = 1024**3
TiB: Final[int] = 1024**4

# AWS S3 max upload parts without having to make additional requests for extra parts
S3_MAX_PARTS = 1_000
S3_MIN_MULTI_UPLOAD_SIZE = 2 * GiB
S3_MAX_MULTI_UPLOAD_SIZE = 5 * TiB

# Minimum size to switch to multipart download, same as upload, 2GB.
MIN_MULTI_DOWNLOAD_SIZE = S3_MIN_MULTI_UPLOAD_SIZE

# Multipart download part size is same as multpart upload size, which is hard coded to 100MB.
# https://github.com/wandb/wandb/blob/7b2a13cb8efcd553317167b823c8e52d8c3f7c4e/core/pkg/artifacts/saver.go#L496
# https://docs.aws.amazon.com/AmazonS3/latest/userguide/optimizing-performance-guidelines.html#optimizing-performance-guidelines-get-range
DOWNLOAD_PART_SIZE = 100 * MiB
# Chunk size for reading http response and writing to disk. 1MB.
HTTP_RSP_CHUNK_SIZE = 1 * MiB


# Signal end of _ChunkQueue, consumer (file writer) should stop after getting this item.
# NOTE: it should only be used for multithread executor, it does notwork for multiprocess executor.
# multipart download is using the executor from artifact.download() which is a multithread executor.
class ChunkSentinel:
    def __repr__(self) -> str:
        return f"<{type(self).__qualname__}>"


CHUNK_SENTINEL: Final[ChunkSentinel] = ChunkSentinel()


@dataclass
class ChunkContent:
    offset: int
    data: bytes


def should_multipart_download(file_size: int, multipart: bool | None) -> bool:
    return (file_size >= MIN_MULTI_DOWNLOAD_SIZE) if (multipart is None) else multipart


DEFAULT_CHUNK_SIZE = 100 * MiB


def calc_chunk_size(file_size: int) -> int:
    # Default to chunk size of 100MiB. S3 has cap of 10,000 upload parts.
    # If file size exceeds the default chunk size, recalculate chunk size.
    return max(math.ceil(file_size / S3_MAX_PARTS), DEFAULT_CHUNK_SIZE)


def scan_chunks(path: str, chunk_size: int) -> Iterator[bytes]:
    with open(path, "rb") as f:
        while data := f.read(chunk_size):
            yield data


def is_chunk_sentinel(item: Any) -> TypeIs[ChunkSentinel]:
    """Returns True if the item is the sentinel value for terminating multipart download."""
    return item is CHUNK_SENTINEL


def multipart_file_download(
    executor: concurrent.futures.Executor,
    session: requests.Session,
    download_url: str,
    size: int,
    cache_open: Opener,
):
    """Download file as multiple parts in parallel.

    Only one thread for writing to file. Each part run one http request in one thread.
    HTTP response chunk of a file part is sent to the writer thread via a queue.
    """
    # Shared between threads
    q: Queue[ChunkContent | ChunkSentinel] = Queue(maxsize=500)
    multipart_error = threading.Event()

    # Put cache_open at top so we remove the tmp file when there is network error.
    with cache_open("wb") as f:
        # Start writer thread first.
        write_future = executor.submit(write_chunks, f, q, multipart_error)

        # Start download threads for each part.
        download_futures = set()
        part_size = DOWNLOAD_PART_SIZE
        for start in range(0, size, part_size):
            # https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Range
            # Start and end are both inclusive, empty end means use the actual end of the file.
            end = start + part_size - 1
            headers = {
                # e.g. bytes=0-499
                "Range": f"bytes={start}-{end}" if (end < size) else f"bytes={start}-"
            }
            download_futures.add(
                executor.submit(
                    download_part,
                    session=session,
                    url=download_url,
                    headers=headers,
                    offset=start,
                    q=q,
                    multipart_error=multipart_error,
                )
            )

        # Wait for download
        done, _ = concurrent.futures.wait(
            download_futures, return_when=concurrent.futures.FIRST_EXCEPTION
        )
        try:
            for fut in done:
                fut.result()
        except Exception as e:
            if env.is_debug():
                logger.debug(f"Error downloading file: {e}")
            multipart_error.set()

            # Cancel any pending futures.  Note:
            # - `Future.cancel()` does NOT stop the future if it's running, which is why
            #   there's a separate `threading.Event` to ensure cooperative cancellation.
            # - Once Python 3.8 support is dropped, replace these `fut.cancel()`
            #   calls with `Executor.shutdown(cancel_futures=True)`.
            for fut in download_futures:
                fut.cancel()

            raise
        finally:
            # Always signal the writer to stop
            q.put(CHUNK_SENTINEL)
            write_future.result()


def download_part(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    offset: int,
    q: Queue,
    multipart_error: threading.Event,
):
    # Error from another thread, no need to start
    if multipart_error.is_set():
        return
    with session.get(url=url, headers=headers, stream=True) as rsp:
        for chunk in rsp.iter_content(chunk_size=HTTP_RSP_CHUNK_SIZE):
            if multipart_error.is_set():
                return
            q.put(ChunkContent(offset=offset, data=chunk))
            offset += len(chunk)


def write_chunks(
    f: IO,
    q: Queue[ChunkContent | ChunkSentinel],
    multipart_error: threading.Event,
):
    # If all chunks are written or there's an error in another thread, shutdown
    while not (multipart_error.is_set() or is_chunk_sentinel(item := q.get())):
        try:
            # NOTE: Seek works without pre allocating the file on disk.
            # It automatically creates a sparse file, e.g. ls -hl would show
            # a bigger size compared to du -sh * because downloading different
            # chunks is not a sequential write.
            # See https://man7.org/linux/man-pages/man2/lseek.2.html
            f.seek(item.offset)
            f.write(item.data)

        except Exception as e:
            if env.is_debug():
                logger.debug(f"Error writing chunk to file: {e}")
            multipart_error.set()
            raise
