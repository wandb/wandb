import asyncio
import logging
import threading
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, List, Optional

import aiofiles
import httpx

from wandb.filesync import stats
from wandb.sdk.interface.artifacts import ArtifactManifest, ArtifactManifestEntry
from wandb.sdk.internal import internal_api

try:
    from typing import TypedDict
except ImportError:
    from typing_extensions import TypedDict


class CreateFileSpec(TypedDict):
    artifactID: str
    artifactManifestID: str
    name: str
    md5: str


logger = logging.getLogger(__name__)


# These are (by design) shared across all uploads, not per-artifact.
UPLOAD_BATCH_SIZE = 50
CONCURRENT_UPLOAD_LIMIT = 500
concurrent_upload_limit = asyncio.Semaphore(CONCURRENT_UPLOAD_LIMIT)
concurrent_batch_limit = asyncio.Semaphore(CONCURRENT_UPLOAD_LIMIT / UPLOAD_BATCH_SIZE)

shared_session = httpx.AsyncClient()


class UploadStatus(Enum):
    PENDING = auto()
    SUCCESS = auto()
    HALTED = auto()
    FAILED = auto()


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

        self.status = UploadStatus.PENDING
        self.done = threading.Event()
        self.background_thread = threading.Thread(target=self._thread_body)

    def join(self, timeout: Optional[float] = None) -> None:
        self.background_thread.join(timeout)

    def _thread_body(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()

        loop.run_until_complete(self._async_body())
        self.done.set()

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
                    self.status = UploadStatus.FAILED
                    return

        self.status = UploadStatus.SUCCESS

    async def _upload_batch(self, batch: List[ArtifactManifestEntry]):
        create_file_specs = [self._file_spec(entry) for entry in batch]
        async with concurrent_batch_limit:
            # TODO(hugh): Move GQLClient to async so we can await here.
            request_store_response = self._api.create_artifact_files(create_file_specs)

        file_upload_tasks = []
        for entry in batch:
            response = request_store_response.get[entry.path]
            file_upload_tasks.append(self._upload_file(entry, response))

        return await asyncio.gather(*file_upload_tasks)

    async def _upload_file(
        self, entry: ArtifactManifestEntry, response: Dict[str, str]
    ):
        try:
            async with concurrent_upload_limit:
                async with aiofiles.open(entry.local_path, "rb") as f:
                    response = await shared_session.put(
                        response["uploadUrl"],
                        content=f,
                        headers=split_headers(response["uploadHeaders"]),
                    )
                    response.raise_for_status()
            self._file_tracker.finish_file(entry.local_path)
        except Exception as e:
            logger.error(
                f"Failed to upload file {entry.local_path} "
                f"to {response['uploadUrl']}: {e}"
            )

    def _file_spec(self, entry: ArtifactManifestEntry) -> CreateFileSpec:
        return CreateFileSpec(
            artifactID=self.artifact_id,
            artifactManifestID=self.manifest_id,
            name=entry.path,
            md5=entry.digest,
        )


def batches(items, batch_size=UPLOAD_BATCH_SIZE):
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]


def split_headers(header_strs: Optional[List[str]]) -> Dict[str, str]:
    return dict(header_str.split(":", 1) for header_str in (header_strs or []))
