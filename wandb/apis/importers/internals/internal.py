import json
import logging
import os
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from unittest.mock import MagicMock

import numpy as np
from google.protobuf.json_format import ParseDict
from rich.logging import RichHandler
from tenacity import retry, stop_after_attempt, wait_random_exponential

from wandb import Artifact
from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_settings_pb2
from wandb.proto import wandb_telemetry_pb2 as telem_pb
from wandb.sdk.interface.interface import file_policy_to_enum
from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.internal import context, sender, settings_static
from wandb.util import cast_dictlike_to_dict, coalesce

from .protocols import ImporterRun

logging.basicConfig(
    handlers=[
        RichHandler(
            rich_tracebacks=True,
            tracebacks_show_locals=True,
        )
    ]
)

logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)

logging.getLogger("import_logger").setLevel(logging.INFO)


exp_retry = retry(
    wait=wait_random_exponential(multiplier=1, max=10), stop=stop_after_attempt(3)
)


class AlternateSendManager(sender.SendManager):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._send_artifact = exp_retry(self._send_artifact)


@dataclass
class ThreadLocalSettings(threading.local):
    src_api_key: str = ""
    src_base_url: str = ""
    src_entity: str = ""
    src_project: str = ""
    src_run_id: str = ""

    dst_api_key: str = ""
    dst_base_url: str = ""


_thread_local_settings = ThreadLocalSettings()


# def set_thread_local_importer_settings(api_key, base_url):
#     _thread_local_settings.src_api_key = api_key
#     _thread_local_settings.src_base_url = base_url


# def set_thread_local_run_settings(entity, project, run_id):
#     _thread_local_settings.src_entity = entity
#     _thread_local_settings.src_project = project
#     _thread_local_settings.src_run_id = run_id


@dataclass(frozen=True)
class SendManagerConfig:
    """Configure which parts of SendManager tooling to use."""

    use_artifacts: bool = False
    log_artifacts: bool = False
    metadata: bool = False
    files: bool = False
    media: bool = False
    code: bool = False
    history: bool = False
    summary: bool = False
    terminal_output: bool = False


@dataclass
class RecordMaker:
    run: ImporterRun
    interface: InterfaceQueue = InterfaceQueue()

    @property
    def run_dir(self) -> str:
        p = Path(f"./wandb-importer/{self.run.run_id()}/wandb")
        p.mkdir(parents=True, exist_ok=True)
        return f"./wandb-importer/{self.run.run_id()}"

    def _make_fake_run_record(self):
        """test.

        Unfortunately, the vanilla Run object does a check for existence on the server,
        so we use this as the simplest hack to skip that check.

        """
        # in this case run is a magicmock, so we need to convert the return types back to vanilla py types
        run = pb.RunRecord()
        run.entity = self.run.run.entity.return_value
        run.project = self.run.run.project.return_value
        run.run_id = self.run.run.run_id.return_value

        return self.interface._make_record(run=run)

    def _make_run_record(self) -> pb.Record:
        # unfortunate hack to get deleted wandb runs to work...
        if hasattr(self.run, "run") and isinstance(self.run.run, MagicMock):
            return self._make_fake_run_record()

        run = pb.RunRecord()
        run.run_id = self.run.run_id()
        run.entity = self.run.entity()
        run.project = self.run.project()
        run.display_name = coalesce(self.run.display_name())
        run.notes = coalesce(self.run.notes(), "")
        run.tags.extend(coalesce(self.run.tags(), []))
        run.start_time.FromMilliseconds(self.run.start_time())

        host = self.run.host()
        if host is not None:
            run.host = host

        runtime = self.run.runtime()
        if runtime is not None:
            run.runtime = runtime

        run_group = self.run.run_group()
        if run_group is not None:
            run.run_group = run_group

        config = self.run.config()
        if "_wandb" not in config:
            config["_wandb"] = {}

        # how do I get this automatically?
        config["_wandb"]["code_path"] = self.run.code_path()
        config["_wandb"]["python_version"] = self.run.python_version()
        config["_wandb"]["cli_version"] = self.run.cli_version()

        self.interface._make_config(
            data=config,
            obj=run.config,
        )  # is there a better way?
        return self.interface._make_record(run=run)

    def _make_output_record(self, line) -> pb.Record:
        output_raw = pb.OutputRawRecord()
        output_raw.output_type = pb.OutputRawRecord.OutputType.STDOUT
        output_raw.line = line
        return self.interface._make_record(output_raw=output_raw)

    def _make_summary_record(self) -> pb.Record:
        d: dict = {
            **self.run.summary(),
            "_runtime": self.run.runtime(),  # quirk of runtime -- it has to be here!
            # '_timestamp': self.run.start_time()/1000,
        }
        d = cast_dictlike_to_dict(d)
        summary = self.interface._make_summary_from_dict(d)
        return self.interface._make_record(summary=summary)

    def _make_history_records(self) -> Iterable[pb.Record]:
        import math

        for metrics in self.run.metrics():
            history = pb.HistoryRecord()
            for k, v in metrics.items():
                item = history.item.add()
                item.key = k
                # There seems to be some conversion issue to breaks when we try to re-upload.
                # np.NaN gets converted to float("nan"), which is not expected by our system.
                # If this cast to string (!) is not done, the row will be dropped.
                if (isinstance(v, float) and math.isnan(v)) or v == "NaN":
                    v = np.NaN
                if isinstance(v, bytes):
                    print("bytes", v)
                    continue
                item.value_json = json.dumps(v)
            rec = self.interface._make_record(history=history)
            yield rec

    def _make_files_record(self, metadata, artifacts, files, media, code) -> pb.Record:
        files = self.run.files()
        metadata_fname = f"{self.run_dir}/files/wandb-metadata.json"
        if files is None:
            metadata_fname = self._make_metadata_file()
            files = [(metadata_fname, "end")]

        files_record = pb.FilesRecord()
        for path, policy in files:
            if not metadata and path == metadata_fname:
                continue
            if not artifacts and path.startswith("artifact/"):
                continue
            if not media and path.startswith("media/"):
                continue
            if not code and path.startswith("code/"):
                continue

            f = files_record.files.add()
            f.path = path
            f.policy = file_policy_to_enum(policy)  # is this always end?

        return self.interface._make_record(files=files_record)

    def _make_artifact_record(self, artifact, use_artifact=False) -> pb.Record:
        proto = self.interface._make_artifact(artifact)
        proto.run_id = str(self.run.run_id())
        proto.project = str(self.run.project())
        proto.entity = str(self.run.entity())
        proto.user_created = use_artifact
        proto.use_after_commit = use_artifact
        proto.finalize = True

        aliases = artifact._aliases
        aliases += ["latest", "imported"]

        for alias in aliases:
            proto.aliases.append(alias)
        return self.interface._make_record(artifact=proto)

    def _make_telem_record(self) -> pb.Record:
        telem = telem_pb.TelemetryRecord()

        feature = telem_pb.Feature()
        feature.importer_mlflow = True
        telem.feature.CopyFrom(feature)

        cli_version = self.run.cli_version()
        if cli_version:
            telem.cli_version = cli_version

        python_version = self.run.python_version()
        if python_version:
            telem.python_version = python_version

        return self.interface._make_record(telemetry=telem)

    def _make_metadata_file(self) -> str:
        missing_text = "This data was not captured"

        d = {}
        d["os"] = coalesce(self.run.os_version(), missing_text)
        d["python"] = coalesce(self.run.python_version(), missing_text)
        d["program"] = coalesce(self.run.program(), missing_text)
        d["cuda"] = coalesce(self.run.cuda_version(), missing_text)
        d["host"] = coalesce(self.run.host(), missing_text)
        d["username"] = coalesce(self.run.username(), missing_text)
        d["executable"] = coalesce(self.run.executable(), missing_text)

        gpus_used = self.run.gpus_used()
        if gpus_used is not None:
            d["gpu_devices"] = json.dumps(gpus_used)
            d["gpu_count"] = json.dumps(len(gpus_used))

        cpus_used = self.run.cpus_used()
        if cpus_used is not None:
            d["cpu_count"] = json.dumps(self.run.cpus_used())

        mem_used = self.run.memory_used()
        if mem_used is not None:
            d["memory"] = json.dumps({"total": self.run.memory_used()})

        fname = f"{self.run_dir}/files/wandb-metadata.json"
        with open(fname, "w") as f:
            f.write(json.dumps(d))
        return fname


def _make_settings(root_dir: str, settings_override: Optional[Dict[str, Any]] = None):
    _settings_override = coalesce(settings_override, {})

    default_settings: Dict[str, Any] = {
        "files_dir": os.path.join(root_dir, "files"),
        "root_dir": root_dir,
        "resume": "false",
        "program": None,
        "ignore_globs": [],
        "disable_job_creation": True,
        "_start_time": 0,
        "_offline": None,
        "_sync": True,
        "_live_policy_rate_limit": 15,  # matches dir_watcher
        "_live_policy_wait_time": 600,  # matches dir_watcher
        "_async_upload_concurrency_limit": None,
        "_file_stream_timeout_seconds": 60,
        # "_import_mode": True,
    }

    combined_settings = {**default_settings, **_settings_override}
    settings_message = wandb_settings_pb2.Settings()
    ParseDict(combined_settings, settings_message)

    return settings_static.SettingsStatic(settings_message)


def _handle_run_record(sm: sender.SendManager, rm: RecordMaker):
    sm.send(rm._make_run_record())


def _handle_telem(sm: sender.SendManager, rm: RecordMaker):
    sm.send(rm._make_telem_record())


def _handle_metadata(
    sm: sender.SendManager, rm: RecordMaker, config: SendManagerConfig
):
    has_artifacts = config.log_artifacts or config.use_artifacts
    sm.send(
        rm._make_files_record(
            config.metadata,
            has_artifacts,
            config.files,
            config.media,
            config.code,
        )
    )


def _handle_use_artifacts(
    sm: sender.SendManager,
    rm: RecordMaker,
    config: SendManagerConfig,
    run_identifier: str,
):
    if config.use_artifacts:
        # task_name = f"Use Artifacts {run_identifier}"
        used_artifacts = rm.run.used_artifacts()
        if used_artifacts is not None:
            used_artifacts = list(used_artifacts)

            # task = progress.subtask_pbar.add_task(task_name, total=len(used_artifacts))
            for artifact in used_artifacts:
                sm.send(rm._make_artifact_record(artifact, use_artifact=True))
                # progress.subtask_pbar.update(task, advance=1)
            # progress.subtask_pbar.remove_task(task)


def _handle_log_artifacts(
    sm: sender.SendManager,
    rm: RecordMaker,
    config: SendManagerConfig,
    run_identifier: str,
):
    if config.log_artifacts:
        # task_name = f"Log Artifacts {run_identifier}"
        artifacts = rm.run.artifacts()
        if artifacts is not None:
            artifacts = list(artifacts)
            # task = progress.subtask_pbar.add_task(task_name, total=len(artifacts))
            for artifact in artifacts:
                sm.send(rm._make_artifact_record(artifact))
                # progress.subtask_pbar.update(task, advance=1)
            # progress.subtask_pbar.remove_task(task)


def _handle_log_specific_artifact(
    sm: sender.SendManager,
    rm: RecordMaker,
    art: Artifact,
    config: SendManagerConfig,
):
    if config.log_artifacts:
        sm.send(rm._make_artifact_record(art))


def _handle_use_specific_artifact(
    sm: sender.SendManager,
    rm: RecordMaker,
    art: Artifact,
    config: SendManagerConfig,
):
    if config.use_artifacts:
        sm.send(rm._make_artifact_record(art, use_artifact=True))


def _handle_history(
    sm: sender.SendManager,
    rm: RecordMaker,
    config: SendManagerConfig,
    run_identifier: str,
):
    if config.history:
        # task_name = f"History {run_identifier}"
        # task = progress.subtask_pbar.add_task(task_name, total=None)
        for history_record in rm._make_history_records():
            sm.send(history_record)
        #     progress.subtask_pbar.update(task, advance=1)
        # progress.subtask_pbar.remove_task(task)


def _handle_summary(sm: sender.SendManager, rm: RecordMaker, config: SendManagerConfig):
    if config.summary:
        sm.send(rm._make_summary_record())


def _handle_terminal_output(
    sm: sender.SendManager,
    rm: RecordMaker,
    config: SendManagerConfig,
    run_identifier: str,
):
    if config.terminal_output:
        # task_name = f"Terminal Output {run_identifier}"
        # task = progress.subtask_pbar.add_task(task_name, total=None)
        lines = rm.run.logs()
        if lines is not None:
            for line in lines:
                sm.send(rm._make_output_record(line))
        #         progress.subtask_pbar.update(task, advance=1)
        # progress.subtask_pbar.remove_task(task)


def _handle_terminal_output_alt(
    sm: sender.SendManager,
    rm: RecordMaker,
    config: SendManagerConfig,
    run_identifier: str,
):
    if config.terminal_output:
        # task_name = f"Terminal Output {run_identifier}"
        # task = progress.subtask_pbar.add_task(task_name, total=None)
        lines = rm.run.logs()
        if lines is not None:
            for line in lines:
                sm.send(rm._make_output_record(line))
        #         progress.subtask_pbar.update(task, advance=1)
        # progress.subtask_pbar.remove_task(task)


def send_run_with_send_manager(
    run: ImporterRun,
    overrides: Optional[Dict[str, Any]] = None,
    settings_override: Optional[Dict[str, Any]] = None,
    config: Optional[SendManagerConfig] = None,
) -> None:
    if config is None:
        config = SendManagerConfig()

    # does this need to be here for pmap?
    if overrides:
        for k, v in overrides.items():
            # `lambda: v` won't work!
            # https://stackoverflow.com/questions/10802002/why-deepcopy-doesnt-create-new-references-to-lambda-function
            setattr(run, k, lambda v=v: v)
    rm = RecordMaker(run)

    root_dir = rm.run_dir
    settings = _make_settings(root_dir, settings_override)

    record_q: queue.Queue = queue.Queue()
    result_q: queue.Queue = queue.Queue()
    interface = InterfaceQueue(record_q=record_q)
    context_keeper = context.ContextKeeper()

    run_identifier = f"{run.entity()}/{run.project()}/{run.run_id()}"

    with AlternateSendManager(
        settings, record_q, result_q, interface, context_keeper
    ) as sm:
        _handle_run_record(sm, rm)
        _handle_telem(sm, rm)
        _handle_metadata(sm, rm, config)
        _handle_use_artifacts(sm, rm, config, run_identifier)
        _handle_log_artifacts(sm, rm, config, run_identifier)
        _handle_history(sm, rm, config, run_identifier)
        _handle_summary(sm, rm, config)
        _handle_terminal_output(sm, rm, config, run_identifier)


def send_artifacts_with_send_manager(
    arts: Iterable[Artifact],
    run: ImporterRun,
    overrides: Optional[Dict[str, Any]] = None,
    settings_override: Optional[Dict[str, Any]] = None,
    config: Optional[SendManagerConfig] = None,
) -> None:
    if config is None:
        config = SendManagerConfig()

    # does this need to be here for pmap?
    if overrides:
        for k, v in overrides.items():
            # `lambda: v` won't work!
            # https://stackoverflow.com/questions/10802002/why-deepcopy-doesnt-create-new-references-to-lambda-function
            setattr(run, k, lambda v=v: v)

    rm = RecordMaker(run)

    root_dir = rm.run_dir
    settings = _make_settings(root_dir, settings_override)

    record_q: queue.Queue = queue.Queue()
    result_q: queue.Queue = queue.Queue()
    interface = InterfaceQueue(record_q=record_q)
    context_keeper = context.ContextKeeper()

    with AlternateSendManager(
        settings, record_q, result_q, interface, context_keeper
    ) as sm:
        _handle_run_record(sm, rm)

        # for art in progress.subsubtask_progress(arts):
        for art in arts:
            _handle_use_specific_artifact(sm, rm, art, config)
            _handle_log_specific_artifact(sm, rm, art, config)
