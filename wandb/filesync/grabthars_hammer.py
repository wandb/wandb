import asyncio
import logging
import threading
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, List, Optional

import aiofiles
import aiohttp

from wandb.filesync import stats
from wandb.sdk.interface.artifacts import ArtifactManifest, ArtifactManifestEntry
from wandb.sdk.internal import internal_api

logger = logging.getLogger(__name__)


UPLOAD_BATCH_SIZE = 50

concurrency_limiter = asyncio.Semaphore(100)

shared_session = aiohttp.ClientSession()


class UploadStatus(Enum):
    PENDING = auto()
    SUCCESS = auto()
    HALTED = auto()
    FAILED = auto()


class GuardedStatus:
    def __init__(self, status: UploadStatus = UploadStatus.PENDING):
        self._status = status
        self._lock = threading.Lock()

    def get(self) -> UploadStatus:
        return self._status

    def set(self, status: UploadStatus) -> None:
        with self._lock:
            if self._status == UploadStatus.PENDING:
                self._status = status
            else:
                logger.warning(
                    f"Attempted to set status to {self._status} "
                    f"but status is already {status}"
                )


@dataclass
class FileUploadRequest:
    entry: ArtifactManifestEntry
    tracker: stats.Stats
    upload_url: Optional[str] = None

    def __post_init__(self):
        self.tracker.init_file(self.entry.local_path, self.entry.size)


class ArtifactFileUploader:
    def __init__(
        self,
        artifact_id: str,
        manifest_id: str,
        manifest: ArtifactManifest,
        file_tracker: stats.Stats,
        api: internal_api.Api,
    ) -> None:
        self.artifact_id = artifact_id
        self.manifest_id = manifest_id
        self.manifest = manifest
        self._file_tracker = file_tracker
        self._api = api

        self.status = GuardedStatus()
        self.background_thread = threading.Thread(target=self._thread_body)
        self.background_thread.start()

    def _thread_body(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()

        loop.run_until_complete(self._async_body())

    async def _async_body(self) -> None:
        entries = [e for e in self.manifest.entries.values() if e.local_path]
        for entry in entries:
            self._file_tracker.init_file(entry.local_path, entry.size)

        batch_tasks = []
        for batch in batches(entries):
            batch_tasks.append(asyncio.create_task(self._upload_batch(batch)))

        for task in asyncio.as_completed(batch_tasks, timeout=60 * 60):
            for result in await task:
                if result is not None:
                    self.status.set(UploadStatus.FAILED)
                    return

        self.status.set(UploadStatus.SUCCESS)

    async def _upload_batch(self, batch: list[ArtifactManifestEntry]):
        create_file_specs = [
            {
                "artifactID": self.artifact_id,
                "artifactManifestID": self.manifest_id,
                "name": entry.path,
                "md5": entry.digest,
            }
            for entry in batch
        ]
        async with concurrency_limiter:
            request_store_response = self._api.create_artifact_files(create_file_specs)

        file_upload_tasks = []
        for entry in batch:
            response = request_store_response.get[entry.path]
            file_upload_tasks.append(self._upload_file(entry, response))

        return await asyncio.gather(*file_upload_tasks)

    async def _upload_file(
        self, entry: ArtifactManifestEntry, response: dict[str, str]
    ):
        try:
            async with concurrency_limiter:
                async with aiofiles.open(entry.local_path, "rb") as f:
                    async with shared_session.put(
                        response.upload_url,
                        data=f,
                        headers=split_headers(response.upload_headers),
                        skip_auto_headers=["Content-Type"],
                    ) as response:
                        response.raise_for_status()
        except Exception as e:
            logger.error(
                f"Failed to upload file {entry.local_path} "
                f"to {response['url']}: {e}"
            )
            return False

        self._file_tracker.finish_file(entry.local_path)
        return True


def batches(items, batch_size=UPLOAD_BATCH_SIZE):
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]


def split_headers(header_strs: Optional[List[str]]) -> Dict[str, str]:
    if header_strs is None:
        return {}
    return dict([header_str.split(":", 1) for header_str in header_strs])
