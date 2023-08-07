import datetime
import logging
import platform
import tempfile
import typing

from wandb import __version__, util
from wandb import errors as wandb_errors
from wandb.apis import public

from .artifacts import artifact_saver
from .data_types.utils import history_dict_to_json
from .interface.interface import InterfaceBase
from .internal import file_stream
from .internal.file_pusher import FilePusher
from .internal.internal_api import Api as InternalApi
from .internal.sender import _manifest_json_from_proto
from .internal.thread_local_settings import _thread_local_api_settings
from .lib import config_util, runid
from .lib.ipython import _get_python_type

if typing.TYPE_CHECKING:
    from wandb.sdk.artifacts.artifact import Artifact

logger = logging.getLogger(__name__)

_p_api = None


def wandb_public_api() -> public.Api:
    global _p_api
    if _p_api is None:
        _p_api = public.Api(timeout=30)
    return _p_api


def assert_wandb_authenticated() -> None:
    authenticated = (
        _thread_local_api_settings.cookies is not None
        or wandb_public_api().api_key is not None
    )
    if not authenticated:
        raise wandb_errors.AuthenticationError(
            "Unable to log data to W&B. Please authenticate by setting WANDB_API_KEY or running `wandb init`."
        )


# We disable urllib warnings because they are noisy and not actionable.
logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)

WANDB_HIDDEN_JOB_TYPE = "sweep-controller"


class _InMemoryLazyLiteRun:
    """This class is only used by StreamTable and will be superseeded in the future.

    It provides a light weight interface to init a run, log data to it and log artifacts.
    """

    # ID
    _entity_name: str
    _project_name: str
    _run_name: str
    _step: int = 0
    _config: typing.Optional[typing.Dict]

    # Optional
    _display_name: typing.Optional[str] = None
    _job_type: typing.Optional[str] = None
    _group: typing.Optional[str] = None

    # Property Cache
    _i_api: typing.Optional[InternalApi] = None
    _run: typing.Optional[public.Run] = None
    _stream: typing.Optional[file_stream.FileStreamApi] = None
    _pusher: typing.Optional[FilePusher] = None
    _server_info: typing.Optional[typing.Dict] = None
    _dir: tempfile.TemporaryDirectory

    def __init__(
        self,
        entity_name: str,
        project_name: str,
        run_name: typing.Optional[str] = None,
        config: typing.Optional[typing.Dict] = None,
        *,
        job_type: typing.Optional[str] = None,
        group: typing.Optional[str] = None,
        _hide_in_wb: bool = False,
    ):
        assert_wandb_authenticated()

        # Technically, we could use the default entity and project here, but
        # heeding Shawn's advice, we should be explicit about what we're doing.
        # We can always move to the default later, but we can't go back.
        if entity_name == "":
            raise ValueError("Must specify entity_name")
        elif project_name == "":
            raise ValueError("Must specify project_name")

        self._entity_name = entity_name
        self._project_name = project_name
        self._display_name = run_name
        self._run_name = run_name or runid.generate_id()
        self._config = config or dict()
        # TODO: wire up actual telemetry?
        self._config.update(
            {
                "_wandb": {
                    "streamtable_version": "0.1",
                    "cli_version": __version__,
                    "python_version": platform.python_version(),
                    "is_jupyter_run": _get_python_type() != "python",
                },
            }
        )
        self._job_type = job_type if not _hide_in_wb else WANDB_HIDDEN_JOB_TYPE
        self._dir = tempfile.TemporaryDirectory()
        if _hide_in_wb and group is None:
            group = "weave_hidden_runs"
        self._group = group

    def ensure_run(self) -> public.Run:
        return self.run

    @property
    def dir(self) -> str:
        return self._dir.name

    @property
    def i_api(self) -> InternalApi:
        if self._i_api is None:
            self._i_api = InternalApi(
                {"project": self._project_name, "entity": self._entity_name}
            )
        return self._i_api

    @property
    def supports_streamtable(self) -> bool:
        # SaaS always supports streamtable
        if self.i_api.settings("base_url").endswith("wandb.ai"):
            return True
        if self._server_info is None:
            _, self._server_info = self.i_api.viewer_server_info()
        return self._server_info.get("streamTableEnabled", False)

    @property
    def id(self) -> str:
        return self._run_name

    @property
    def project(self) -> str:
        return self._project_name

    @property
    def run(self) -> public.Run:
        if self._run is None:
            # TODO: decide if we want to merge an existing run
            # Produce a run
            run_res, _, _ = self.i_api.upsert_run(
                name=self._run_name,
                display_name=self._display_name,
                job_type=self._job_type,
                config=config_util.dict_add_value_dict(self._config),  # type: ignore[no-untyped-call]
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

        return self._run

    @property
    def stream(self) -> file_stream.FileStreamApi:
        if self._stream is None:
            # Setup the FileStream
            self._stream = file_stream.FileStreamApi(
                self.i_api, self.run.id, datetime.datetime.utcnow().timestamp()
            )
            self._stream._client.headers.update(
                {"X-WANDB-USE-ASYNC-FILESTREAM": "true"}
            )
            self._stream.set_file_policy(
                "wandb-history.jsonl",
                file_stream.JsonlFilePolicy(start_chunk_id=0),
            )
            self._stream.start()

        return self._stream

    @property
    def pusher(self) -> FilePusher:
        if self._pusher is None:
            self._pusher = FilePusher(self.i_api, self.stream)

        return self._pusher

    def log_artifact(
        self, artifact: "Artifact", additional_aliases: typing.Optional[list] = None
    ) -> typing.Optional[dict]:
        if additional_aliases is None:
            additional_aliases = []
        # Ensure type is created
        self.i_api.create_artifact_type(
            artifact_type_name=artifact.type,
            entity_name=self.run.entity,
            project_name=self.run.project,
        )
        artifact.finalize()
        ## TODO: use a cleaner interace here
        manifest_dict = _manifest_json_from_proto(
            InterfaceBase()._make_artifact(artifact).manifest  # type: ignore[abstract, attr-defined]
        )
        saver = artifact_saver.ArtifactSaver(
            api=self.i_api,
            digest=artifact.digest,
            manifest_json=manifest_dict,
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
            aliases=["latest"] + additional_aliases,
            use_after_commit=False,
            finalize=True,
        )

    def log(self, row_dict: dict) -> None:
        stream = self.stream
        row_dict = {
            **row_dict,
            "_timestamp": datetime.datetime.utcnow().timestamp(),
        }
        # TODO: we're always setting step to 0 here, this will overwrite media
        processed_dict = history_dict_to_json(self, row_dict, step=0)
        stream.push(
            "wandb-history.jsonl", util.json_dumps_safer_history(processed_dict)
        )

    def finish(self) -> None:
        if self._stream is not None:
            # Finalize the run
            self.stream.finish(0)

        if self._pusher is not None:
            # Wait for the FilePusher and FileStream to finish
            self.pusher.finish()
            self.pusher.join()

        # Cleanup any files
        self.dir.cleanup()

        # Reset fields
        self._stream = None
        self._pusher = None
        self._run = None
        self._i_api = None

    def __del__(self) -> None:
        self.finish()
