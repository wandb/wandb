import datetime
import logging
import os
import typing

import wandb
from wandb import errors as wandb_errors
from wandb import util
from wandb.apis import public

from .artifacts import artifact_saver
from .internal import file_stream
from .internal.file_pusher import FilePusher
from .internal.internal_api import Api as InternalApi
from .internal.internal_api import _thread_local_api_settings
from .lib import runid

logger = logging.getLogger(__name__)


def wandb_public_api() -> public.Api:
    return public.Api(timeout=30)


def assert_wandb_authenticated() -> None:
    authenticated = (
        wandb_public_api().api_key is not None
        or _thread_local_api_settings.cookies is not None
    )
    if not authenticated:
        raise wandb_errors.AuthenticationError(
            "Unable to log data to W&B. Please authenticate by setting WANDB_API_KEY or running `wandb init`."
        )


# We disable urllib warnings because they are noisy and not actionable.
logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)

WANDB_HIDDEN_JOB_TYPE = "sweep-controller"


class InMemoryLazyLiteRun:
    # ID
    _entity_name: str
    _project_name: str
    _run_name: str
    _step: int = 0

    # Optional
    _display_name: typing.Optional[str] = None
    _job_type: typing.Optional[str] = None
    _group: typing.Optional[str] = None

    # Property Cache
    _i_api: typing.Optional[InternalApi] = None
    _run: typing.Optional[public.Run] = None
    _stream: typing.Optional[file_stream.FileStreamApi] = None
    _pusher: typing.Optional[FilePusher] = None
    _use_async_file_stream: bool = False

    def __init__(
        self,
        entity_name: str,
        project_name: str,
        run_name: typing.Optional[str] = None,
        *,
        job_type: typing.Optional[str] = None,
        group: typing.Optional[str] = None,
        _hide_in_wb: bool = False,
        _use_async_file_stream: bool = False,
    ):
        assert_wandb_authenticated()

        # Technically, we could use the default entity and project here, but
        # heeding Shawn's advice, we should be explicit about what we're doing.
        # We can always move to the default later, but we can't go back.
        if entity_name is None or entity_name == "":
            raise ValueError("Must specify entity_name")
        elif project_name is None or project_name == "":
            raise ValueError("Must specify project_name")

        self._entity_name = entity_name
        self._project_name = project_name
        self._display_name = run_name
        self._run_name = run_name or runid.generate_id()
        self._job_type = job_type if not _hide_in_wb else WANDB_HIDDEN_JOB_TYPE
        if _hide_in_wb and group is None:
            group = "weave_hidden_runs"
        self._group = group

        self._use_async_file_stream = (
            _use_async_file_stream
            and os.getenv("WEAVE_DISABLE_ASYNC_FILE_STREAM") is None
        )

    def ensure_run(self) -> public.Run:
        return self.run

    @property
    def i_api(self) -> InternalApi:
        if self._i_api is None:
            self._i_api = InternalApi(
                {"project": self._project_name, "entity": self._entity_name}
            )
        return self._i_api

    @property
    def run(self) -> public.Run:
        if self._run is None:
            # Ensure project exists
            self.i_api.upsert_project(
                project=self._project_name, entity=self._entity_name
            )

            # Produce a run
            run_res, _, _ = self.i_api.upsert_run(
                name=self._run_name,
                display_name=self._display_name,
                job_type=self._job_type,
                group=self._group,
                project=self._project_name,
                entity=self._entity_name,
            )

            self._run = public.Run(
                wandb_public_api().client,
                run_res["project"]["entity"]["name"],
                run_res["project"]["name"],
                run_res["name"],
                {
                    "id": run_res["id"],
                    "config": "{}",
                    "systemMetrics": "{}",
                    "summaryMetrics": "{}",
                    "tags": [],
                    "description": None,
                    "notes": None,
                    "state": "running",
                },
            )

            self.i_api.set_current_run_id(self._run.id)
            # No need to get the last step if we're using the async file stream
            if self._use_async_file_stream:
                self._step = 0
            else:
                self._step = self._run.lastHistoryStep + 1

        return self._run

    @property
    def stream(self) -> file_stream.FileStreamApi:
        if self._stream is None:
            # Setup the FileStream
            self._stream = file_stream.FileStreamApi(
                self.i_api, self.run.id, datetime.datetime.utcnow().timestamp()
            )
            if self._use_async_file_stream:
                self._stream._client.headers.update(
                    {"X-WANDB-USE-ASYNC-FILESTREAM": "true"}
                )
            self._stream.set_file_policy(
                "wandb-history.jsonl",
                file_stream.JsonlFilePolicy(start_chunk_id=self._step),
            )
            self._stream.start()

        return self._stream

    @property
    def pusher(self) -> FilePusher:
        if self._pusher is None:
            self._pusher = FilePusher(self.i_api, self.stream)

        return self._pusher

    def log_artifact(self, artifact: "wandb.Artifact") -> typing.Optional[dict]:
        saver = artifact_saver.ArtifactSaver(
            api=self.i_api,
            digest=artifact.digest,
            manifest_json=artifact.manifest.to_manifest_json(),
            file_pusher=self.pusher,
            is_user_created=False,
        )
        return saver.save(
            type=artifact.type,
            name=artifact.name,
            client_id=artifact._client_id,
            sequence_client_id=artifact._sequence_client_id,
            metadata=artifact.metadata,
            description=artifact.description or None,
            aliases=artifact._aliases,
            use_after_commit=False,
            distributed_id=None,
            finalize=artifact.finalize,
            incremental=False,
            history_step=0,
            base_id=artifact._base_id or None,
        )

    def log(self, row_dict: dict) -> None:
        stream = self.stream
        row_dict = {
            **row_dict,
            "_timestamp": datetime.datetime.utcnow().timestamp(),
        }
        if not self._use_async_file_stream:
            row_dict["_step"] = self._step
        self._step += 1
        stream.push("wandb-history.jsonl", util.json_dumps_safer_history(row_dict))

    def finish(self) -> None:
        if self._stream is not None:
            # Finalize the run
            self.stream.finish(0)

        if self._pusher is not None:
            # Wait for the FilePusher and FileStream to finish
            self.pusher.finish()
            self.pusher.join()

        # Reset fields
        self._stream = None
        self._pusher = None
        self._run = None
        self._i_api = None
        self._step = 0

    def __del__(self) -> None:
        self.finish()
