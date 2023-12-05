import json
import os
import queue
import sys
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple
from unittest.mock import patch

from google.protobuf.json_format import ParseDict
from tqdm import tqdm

import wandb
from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_settings_pb2
from wandb.proto import wandb_telemetry_pb2 as telem_pb
from wandb.sdk.interface.interface import file_policy_to_enum
from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.internal import context
from wandb.sdk.internal.sender import SendManager
from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.util import cast_dictlike_to_dict, coalesce

if sys.version_info >= (3, 8):
    from typing import Protocol
else:
    from typing_extensions import Protocol


with patch("click.echo"):
    from wandb.apis.reports import Report


class ImporterRun(Protocol):
    def run_id(self) -> str:
        ...

    def entity(self) -> str:
        ...

    def project(self) -> str:
        ...

    def config(self) -> Dict[str, Any]:
        ...

    def summary(self) -> Dict[str, float]:
        ...

    def metrics(self) -> Iterable[Dict[str, float]]:
        """Metrics for the run.

        We expect metrics in this shape:

        [
            {'metric1': 1, 'metric2': 1, '_step': 0},
            {'metric1': 2, 'metric2': 4, '_step': 1},
            {'metric1': 3, 'metric2': 9, '_step': 2},
            ...
        ]

        You can also submit metrics in this shape:
        [
            {'metric1': 1, '_step': 0},
            {'metric2': 1, '_step': 0},
            {'metric1': 2, '_step': 1},
            {'metric2': 4, '_step': 1},
            ...
        ]
        """
        ...

    def run_group(self) -> Optional[str]:
        ...

    def job_type(self) -> Optional[str]:
        ...

    def display_name(self) -> str:
        ...

    def notes(self) -> Optional[str]:
        ...

    def tags(self) -> Optional[List[str]]:
        ...

    def artifacts(self) -> Optional[Iterable[wandb.Artifact]]:  # type: ignore
        ...

    def used_artifacts(self) -> Optional[Iterable[wandb.Artifact]]:  # type: ignore
        ...

    def os_version(self) -> Optional[str]:
        ...

    def python_version(self) -> Optional[str]:
        ...

    def cuda_version(self) -> Optional[str]:
        ...

    def program(self) -> Optional[str]:
        ...

    def host(self) -> Optional[str]:
        ...

    def username(self) -> Optional[str]:
        ...

    def executable(self) -> Optional[str]:
        ...

    def gpus_used(self) -> Optional[str]:
        ...

    def cpus_used(self) -> Optional[int]:  # can we get the model?
        ...

    def memory_used(self) -> Optional[int]:
        ...

    def runtime(self) -> Optional[int]:
        ...

    def start_time(self) -> Optional[int]:
        ...

    def code_path(self) -> Optional[str]:
        ...

    def cli_version(self) -> Optional[str]:
        ...

    def files(self) -> Optional[Iterable[Tuple[str, str]]]:
        ...

    def logs(self) -> Optional[Iterable[str]]:
        ...


class Importer(Protocol):
    def collect_runs(self, *args, **kwargs) -> Iterable[ImporterRun]:
        ...

    def collect_reports(self, *args, **kwargs) -> Iterable[Report]:
        ...

    def import_run(self, run: ImporterRun) -> None:
        ...

    def import_report(self, report: Report) -> None:
        ...


@dataclass
class RecordMaker:
    run: ImporterRun
    interface: InterfaceQueue = InterfaceQueue()

    @property
    def run_dir(self) -> str:
        return f"./wandb-importer/{self.run.run_id()}"

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
        d = cast_dictlike_to_dict(d)
        summary = self.interface._make_summary_from_dict(d)
        return self.interface._make_record(summary=summary)

    def _make_history_records(self) -> Iterable[pb.Record]:
        for _, metrics in enumerate(self.run.metrics()):
            history = pb.HistoryRecord()
            for k, v in metrics.items():
                item = history.item.add()
                item.key = k
                item.value_json = json.dumps(v)
            yield self.interface._make_record(history=history)

    def _make_files_record(
        self,
        files_dict,
    ) -> pb.Record:
        files_record = pb.FilesRecord()
        for path, policy in files_dict["files"]:
            f = files_record.files.add()
            f.path = path
            f.policy = file_policy_to_enum(policy)  # is this always "end"?
        return self.interface._make_record(files=files_record)

    def _make_metadata_files_record(self) -> pb.Record:
        files = self.run.files()
        if files is None:
            metadata_fname = self._make_metadata_file()
            files = [(metadata_fname, "end")]

        files_dict = {"files": files}
        return self._make_files_record(files_dict)

    def _make_artifact_record(self, artifact, use_artifact=False) -> pb.Record:
        proto = self.interface._make_artifact(artifact)
        proto.run_id = self.run.run_id()
        proto.project = self.run.project()
        proto.entity = self.run.entity()
        proto.user_created = use_artifact
        proto.use_after_commit = use_artifact
        proto.finalize = True
        for tag in ["latest", "imported"]:
            proto.aliases.append(tag)
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


def send_run_with_send_manager(
    run: ImporterRun,
    overrides: Optional[Dict[str, Any]] = None,
    settings_override: Optional[SettingsStatic] = None,
) -> None:
    # does this need to be here for pmap?
    if overrides:
        for k, v in overrides.items():
            # `lambda: v` won't work!
            # https://stackoverflow.com/questions/10802002/why-deepcopy-doesnt-create-new-references-to-lambda-function
            setattr(run, k, lambda v=v: v)
    _settings_override = coalesce(settings_override, {})
    rm = RecordMaker(run)

    root_dir = rm.run_dir
    default_settings = {
        "files_dir": os.path.join(root_dir, "files"),
        "root_dir": root_dir,
        "_start_time": 0,
        "git_remote": None,
        "resume": False,
        "program": None,
        "ignore_globs": (),
        "run_id": None,
        "entity": None,
        "project": None,
        "run_group": None,
        "job_type": None,
        "run_tags": None,
        "run_name": None,
        "run_notes": None,
        "save_code": None,
        "email": None,
        "silent": None,
        "_offline": None,
        "_sync": True,
        "_live_policy_rate_limit": None,
        "_live_policy_wait_time": None,
        "disable_job_creation": False,
        "_async_upload_concurrency_limit": None,
    }
    combined_settings = {**default_settings, **_settings_override}
    settings_message = wandb_settings_pb2.Settings()
    ParseDict(combined_settings, settings_message)

    settings = SettingsStatic(settings_message)

    record_q: queue.Queue = queue.Queue()
    result_q: queue.Queue = queue.Queue()
    interface = InterfaceQueue(record_q=record_q)
    context_keeper = context.ContextKeeper()

    with SendManager(settings, record_q, result_q, interface, context_keeper) as sm:
        wandb.termlog(">> Make run record")
        sm.send(rm._make_run_record())

        wandb.termlog(">> Use Artifacts")
        used_artifacts = run.used_artifacts()
        if used_artifacts is not None:
            for artifact in tqdm(
                used_artifacts, desc="Used artifacts", unit="artifacts", leave=False
            ):
                sm.send(rm._make_artifact_record(artifact, use_artifact=True))

        wandb.termlog(">> Log Artifacts")
        artifacts = run.artifacts()
        if artifacts is not None:
            for artifact in tqdm(
                artifacts, desc="Logged artifacts", unit="artifacts", leave=False
            ):
                sm.send(rm._make_artifact_record(artifact))

        wandb.termlog(">> Log Metadata")
        sm.send(rm._make_metadata_files_record())

        wandb.termlog(">> Log History")
        for history_record in tqdm(
            rm._make_history_records(), desc="History", unit="steps", leave=False
        ):
            sm.send(history_record)

        wandb.termlog(">> Log Summary")
        sm.send(rm._make_summary_record())

        wandb.termlog(">> Log Output")
        # if hasattr(run, "_logs"):
        #     lines = run._logs
        lines = run.logs()
        if lines is not None:
            for line in tqdm(lines, desc="Stdout", unit="lines", leave=False):
                sm.send(rm._make_output_record(line))

        wandb.termlog(">> Log Telem")
        sm.send(rm._make_telem_record())
