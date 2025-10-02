import json
import logging
import math
import os
import queue
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import numpy as np
from tenacity import retry, stop_after_attempt, wait_random_exponential

from wandb import Artifact
from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_telemetry_pb2 as telem_pb
from wandb.sdk.interface.interface import file_policy_to_enum
from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.internal import context
from wandb.sdk.internal.sender import SendManager
from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.util import coalesce, recursive_cast_dictlike_to_dict

from .protocols import ImporterRun

ROOT_DIR = "./wandb-importer"


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

if os.getenv("WANDB_IMPORTER_ENABLE_RICH_LOGGING"):
    from rich.logging import RichHandler

    logger.addHandler(RichHandler(rich_tracebacks=True, tracebacks_show_locals=True))
else:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(formatter)

    logger.addHandler(console_handler)


exp_retry = retry(
    wait=wait_random_exponential(multiplier=1, max=10), stop=stop_after_attempt(3)
)


class AlternateSendManager(SendManager):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._send_artifact = exp_retry(self._send_artifact)


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
        p = Path(f"{ROOT_DIR}/{self.run.run_id()}/wandb")
        p.mkdir(parents=True, exist_ok=True)
        return f"{ROOT_DIR}/{self.run.run_id()}"

    def make_artifacts_only_records(
        self,
        artifacts: Optional[Iterable[Artifact]] = None,
        used_artifacts: Optional[Iterable[Artifact]] = None,
    ) -> Iterable[pb.Record]:
        """Only make records required to upload artifacts.

        Escape hatch for adding extra artifacts to a run.
        """
        yield self._make_run_record()

        if used_artifacts:
            for art in used_artifacts:
                yield self._make_artifact_record(art, use_artifact=True)

        if artifacts:
            for art in artifacts:
                yield self._make_artifact_record(art)

    def make_records(
        self,
        config: SendManagerConfig,
    ) -> Iterable[pb.Record]:
        """Make all the records that constitute a run."""
        yield self._make_run_record()
        yield self._make_telem_record()

        include_artifacts = config.log_artifacts or config.use_artifacts
        yield self._make_files_record(
            include_artifacts, config.files, config.media, config.code
        )

        if config.use_artifacts:
            if (used_artifacts := self.run.used_artifacts()) is not None:
                for artifact in used_artifacts:
                    yield self._make_artifact_record(artifact, use_artifact=True)

        if config.log_artifacts:
            if (artifacts := self.run.artifacts()) is not None:
                for artifact in artifacts:
                    yield self._make_artifact_record(artifact)

        if config.history:
            yield from self._make_history_records()

        if config.summary:
            yield self._make_summary_record()

        if config.terminal_output:
            if (lines := self.run.logs()) is not None:
                for line in lines:
                    yield self._make_output_record(line)

    def _make_run_record(self) -> pb.Record:
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
        d = recursive_cast_dictlike_to_dict(d)
        summary = self.interface._make_summary_from_dict(d)
        return self.interface._make_record(summary=summary)

    def _make_history_records(self) -> Iterable[pb.Record]:
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
                    # it's a json string encoded as bytes
                    v = v.decode("utf-8")
                else:
                    v = json.dumps(v)

                item.value_json = v
            rec = self.interface._make_record(history=history)
            yield rec

    def _make_files_record(
        self, artifacts: bool, files: bool, media: bool, code: bool
    ) -> pb.Record:
        run_files = self.run.files()
        metadata_fname = f"{self.run_dir}/files/wandb-metadata.json"
        if not files or run_files is None:
            # We'll always need a metadata file even if there are no other files to upload
            metadata_fname = self._make_metadata_file()
            run_files = [(metadata_fname, "end")]
        files_record = pb.FilesRecord()
        for path, policy in run_files:
            if not artifacts and path.startswith("artifact/"):
                continue
            if not media and path.startswith("media/"):
                continue
            if not code and path.startswith("code/"):
                continue

            # DirWatcher requires the path to start with media/ instead of the full path
            if "media" in path:
                p = Path(path)
                path = str(p.relative_to(f"{self.run_dir}/files"))
            f = files_record.files.add()
            f.path = path
            f.policy = file_policy_to_enum(policy)

        return self.interface._make_record(files=files_record)

    def _make_artifact_record(
        self, artifact: Artifact, use_artifact=False
    ) -> pb.Record:
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
        files_dir = f"{self.run_dir}/files"
        os.makedirs(files_dir, exist_ok=True)

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

        fname = f"{files_dir}/wandb-metadata.json"
        with open(fname, "w") as f:
            f.write(json.dumps(d))
        return fname


def _make_settings(
    root_dir: str, settings_override: Optional[Dict[str, Any]] = None
) -> SettingsStatic:
    _settings_override = coalesce(settings_override, {})

    return SettingsStatic(
        {
            "x_files_dir": os.path.join(root_dir, "files"),
            "root_dir": root_dir,
            "resume": "never",
            "program": None,
            "ignore_globs": [],
            "disable_job_creation": True,
            "x_start_time": 0,
            "x_sync": True,
            "x_live_policy_rate_limit": 15,  # matches dir_watcher
            "x_live_policy_wait_time": 600,  # matches dir_watcher
            "x_file_stream_timeout_seconds": 60,
            **_settings_override,
        }
    )


def send_run(
    run: ImporterRun,
    *,
    extra_arts: Optional[Iterable[Artifact]] = None,
    extra_used_arts: Optional[Iterable[Artifact]] = None,
    config: Optional[SendManagerConfig] = None,
    overrides: Optional[Dict[str, Any]] = None,
    settings_override: Optional[Dict[str, Any]] = None,
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
    sm_record_q = queue.Queue()
    # wm_record_q = queue.Queue()
    result_q = queue.Queue()
    interface = InterfaceQueue(record_q=sm_record_q)
    context_keeper = context.ContextKeeper()
    sm = AlternateSendManager(
        settings, sm_record_q, result_q, interface, context_keeper
    )

    if extra_arts or extra_used_arts:
        records = rm.make_artifacts_only_records(extra_arts, extra_used_arts)
    else:
        records = rm.make_records(config)

    for r in records:
        logger.debug(f"Sending {r=}")
        # In a future update, it might be good to write to a transaction log and have
        # incremental uploads only send the missing records.
        # wm.write(r)

        sm.send(r)

    sm.finish()
    # wm.finish()
