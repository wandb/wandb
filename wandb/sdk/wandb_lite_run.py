import datetime
import json
import logging
import os
import platform
import tempfile
import typing

from wandb import __version__, util
from wandb import errors as wandb_errors
from wandb.apis import public

from .artifacts import artifact_saver
from .artifacts.artifact import Artifact
from .data_types.utils import history_dict_to_weave
from .interface.interface import InterfaceBase
from .internal import file_stream
from .internal.file_pusher import FilePusher
from .internal.internal_api import Api as InternalApi
from .internal.sender import _manifest_json_from_proto
from .internal.thread_local_settings import _thread_local_api_settings
from .lib import config_util, proto_util, runid, telemetry
from .lib.ipython import _get_python_type
from .lib.paths import StrPath
from .wandb_settings import Settings

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
    _init_pid: int
    _attach_id: typing.Optional[str]
    _settings: Settings

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
    _dir: typing.Optional[tempfile.TemporaryDirectory] = None

    # Telemetry
    _telemetry_obj: telemetry.TelemetryRecord
    _telemetry_obj_active: bool
    _telemetry_obj_dirty: bool
    _telemetry_obj_flushed: bytes

    def __init__(
        self,
        entity_name: str,
        project_name: str,
        run_name: typing.Optional[str] = None,
        config: typing.Optional[typing.Dict] = None,
        settings: typing.Optional[Settings] = None,
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
        self._settings = settings or Settings()
        self._setup_telemetry()
        self._config = config or dict()
        self._config.update(
            {
                "_wandb": {
                    "cli_version": __version__,
                    "python_version": platform.python_version(),
                    "is_jupyter_run": _get_python_type() != "python",
                    "t": proto_util.proto_encode_to_dict(self._telemetry_obj),
                },
            }
        )
        self._job_type = job_type if not _hide_in_wb else WANDB_HIDDEN_JOB_TYPE
        self._dir = tempfile.TemporaryDirectory()
        if _hide_in_wb and group is None:
            group = "weave_hidden_runs"
        self._group = group
        self._init_pid = os.getpid()
        self._attach_id = self._run_name

    def ensure_run(self) -> public.Run:
        return self.run

    def _add_singleton(
        self, data_type: str, key: str, value: typing.Dict[typing.Union[int, str], str]
    ) -> None:
        raise NotImplementedError("Not implemented for _InMemoryLazyLiteRun")

    @property
    def dir(self) -> str:
        return str(self._dir)

    def _setup_telemetry(self) -> None:
        self._telemetry_obj = telemetry.TelemetryRecord()
        self._telemetry_obj_active = False
        self._telemetry_obj_flushed = b""
        self._telemetry_obj_dirty = False
        with telemetry.context(self, self._telemetry_obj) as tel:
            tel.cli_version = __version__
            tel.python_version = platform.python_version()
            if self._settings._jupyter:
                tel.env.jupyter = True
            if self._settings._ipython:
                tel.env.ipython = True
            if self._settings._colab:
                tel.env.colab = True
            if self._settings._kaggle:
                tel.env.kaggle = True
            if self._settings._windows:
                tel.env.windows = True
            tel.feature.stream_table = True
            for module_name in telemetry.list_telemetry_imports(only_imported=True):
                setattr(tel.imports_init, module_name, True)

    def _telemetry_callback(self, telem_obj: telemetry.TelemetryRecord) -> None:
        # TODO: support config updating, this is currently a no-op
        pass

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
    def entity(self) -> str:
        return self._entity_name

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
                    "config": json.dumps(self._config),
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
        # TODO: figure out how to trigger file uploads
        if self._pusher is None:
            self._pusher = FilePusher(self.i_api, self.stream)

        return self._pusher

    def log_artifact(
        self,
        artifact: typing.Union[Artifact, StrPath],
        name: typing.Optional[str] = None,
        type: typing.Optional[str] = None,
        aliases: typing.Optional[typing.List[str]] = None,
    ) -> Artifact:
        if aliases is None:
            aliases = []
        if not isinstance(artifact, Artifact):
            raise AttributeError("We don't support logging paths in this interface")
        artifact.finalize()
        ## TODO: use a cleaner interace here
        manifest_dict = _manifest_json_from_proto(
            InterfaceBase()._make_artifact(artifact).manifest  # type: ignore[abstract]
        )
        saver = artifact_saver.ArtifactSaver(
            api=self.i_api,
            digest=artifact.digest,
            manifest_json=manifest_dict,
            file_pusher=self.pusher,
            is_user_created=False,
        )
        saver.save(
            type=artifact.type,
            name=artifact.name,
            client_id=artifact._client_id,
            sequence_client_id=artifact._sequence_client_id,
            metadata=artifact.metadata,
            description=artifact.description or None,
            aliases=["latest"] + aliases,
            use_after_commit=False,
            finalize=True,
        )
        return artifact

    def log(
        self,
        row_dict: typing.Dict[str, typing.Any],
        step: typing.Optional[int] = None,
        commit: typing.Optional[bool] = None,
        sync: typing.Optional[bool] = None,
    ) -> None:
        stream = self.stream
        row_dict = {
            **row_dict,
            "_timestamp": datetime.datetime.utcnow().timestamp(),
        }
        processed_dict = history_dict_to_weave(self, row_dict)
        stream.push("wandb-history.jsonl", util.json_dumps_weave(processed_dict))

    def finish(
        self,
        exit_code: typing.Optional[int] = None,
        quiet: typing.Optional[bool] = None,
    ) -> None:
        if self._stream is not None:
            # Finalize the run
            self.stream.finish(0)

        if self._pusher is not None:
            # Wait for the FilePusher and FileStream to finish
            self.pusher.finish()
            self.pusher.join()

        # Cleanup any files
        if self._dir is not None:
            self._dir.cleanup()

        # Reset fields
        self._stream = None
        self._pusher = None
        self._run = None
        self._i_api = None

    def __del__(self) -> None:
        self.finish()
