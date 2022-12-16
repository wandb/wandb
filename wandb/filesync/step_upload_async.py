import asyncio
import queue
import threading
from typing import TYPE_CHECKING, Awaitable, TypeVar, Union

import wandb
from wandb.filesync import stats
from . import step_upload as step_upload_sync

if TYPE_CHECKING:
    from wandb.sdk.internal import file_stream, internal_api

Command = Union[
    step_upload_sync.RequestUpload,
    step_upload_sync.RequestCommitArtifact,
    step_upload_sync.RequestFinish,
]


_T = TypeVar("_T")


class StepUploadAsync:
    """This class aims to be a drop-in replacement for StepUpload, but using asyncio under the hood instead of threading.
    """

    def __init__(
        self,
        api: "internal_api.Api",
        stats: "stats.Stats",
        event_queue: "queue.Queue[Command]",
        max_jobs: int,
        file_stream: "file_stream.FileStreamApi",
        silent: bool = False,
    ) -> None:
        self._api = api
        self._stats = stats
        self._event_queue = event_queue
        self._file_stream = file_stream

        self._loop = asyncio.new_event_loop()
        self._semaphore = asyncio.Semaphore(max_jobs, loop=self._loop)

        self._cmd_finished_cond = asyncio.Condition(loop=self._loop)
        self._unfinished_cmds = set()

        self._artifact_failures = {}

        self._run_loop_thread = threading.Thread(target=self._run_sync, daemon=True)

    def _run_sync(self) -> None:
        finish = self._loop.run_until_complete(self.run())
        if finish.callback is not None:
            finish.callback()

    async def run(self) -> step_upload_sync.RequestFinish:
        while True:
            cmd = await self._loop.run_in_executor(None, self._event_queue.get)
            print("got", cmd)
            if isinstance(cmd, step_upload_sync.RequestFinish):
                return cmd

            self._unfinished_cmds.add(cmd)
            asyncio.create_task(self._handle_cmd(cmd))

    async def _handle_cmd(self, cmd: Command) -> None:
        async with self._semaphore:
            print('handling', cmd)
            try:
                if isinstance(cmd, step_upload_sync.RequestUpload):
                    try:
                        await self._do_upload(cmd)
                    except Exception as e:
                        if cmd.artifact_id is not None:
                            self._artifact_failures[cmd.artifact_id] = e
                elif isinstance(cmd, step_upload_sync.RequestCommitArtifact):
                    await self._do_commit_artifact(cmd)
            finally:
                print("finished", cmd)
                async with self._cmd_finished_cond:
                    self._unfinished_cmds.remove(cmd)
                    self._cmd_finished_cond.notify_all()

    async def _do_upload(self, cmd: step_upload_sync.RequestUpload) -> None:
        _, upload_headers, result = self._api.upload_urls("TODO", [cmd.save_name])
        file_info = result[cmd.save_name]
        upload_url = file_info["url"]
        with open(cmd.path, "rb") as f:
            print("about to upload", cmd)
            await self._loop.run_in_executor(None, lambda: self._api.upload_file_retry(
                upload_url,
                f,
                lambda _, t: self.progress(t),
                extra_headers=dict(h.split(": ", 1) for h in upload_headers),
            ))
            print("done uploading", cmd)

        self._file_stream.push_success(cmd.artifact_id, cmd.save_name)

    async def _do_commit_artifact(self, cmd: step_upload_sync.RequestCommitArtifact) -> None:
        try:
            await self._wait_for_all_artifact_uploads_to_finish(cmd.artifact_id)
        except Exception as e:
            wandb.termerror(
                "Uploading artifact file failed. Artifact won't be committed. " + str(e)
            )
            return


        if cmd.before_commit is not None:
            await self._loop.run_in_executor(None, cmd.before_commit)

        if cmd.finalize:
            await self._loop.run_in_executor(None, self._api.commit_artifact, cmd.artifact_id)

        if cmd.on_commit is not None:
            await self._loop.run_in_executor(None, cmd.on_commit)

    async def _wait_for_all_artifact_uploads_to_finish(self, artifact_id: str) -> None:
        async with self._cmd_finished_cond:
            while any(isinstance(cmd, step_upload_sync.RequestUpload) and cmd.artifact_id == artifact_id for cmd in self._unfinished_cmds) and artifact_id not in self._artifact_failures:  # TODO: optimize
                await self._cmd_finished_cond.wait()

        if artifact_id in self._artifact_failures:
            raise self._artifact_failures[artifact_id]

    async def _wait_until_idle(self) -> None:
        async with self._cmd_finished_cond:
            while self._unfinished_cmds:
                await self._cmd_finished_cond.wait()

    def start(self) -> None:
        self._run_loop_thread.start()

    def is_alive(self) -> bool:
        return True
