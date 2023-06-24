import json
import threading
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Protocol, Tuple
from unittest.mock import patch

from tqdm import tqdm

import wandb
from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_telemetry_pb2 as telem_pb
from wandb.sdk.interface.interface import file_policy_to_enum
from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.internal.sender import SendManager
from wandb.util import cast_dictlike_to_dict, coalesce

with patch("click.echo"):
    import wandb.apis.reports as wr


@dataclass
class ThreadLocalSettings(threading.local):
    api_key: str = ""
    base_url: str = ""


_thread_local_settings = ThreadLocalSettings()


def set_thread_local_settings(api_key, base_url):
    _thread_local_settings.api_key = api_key
    _thread_local_settings.base_url = base_url


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

    def artifacts(self) -> Optional[Iterable[wandb.Artifact]]:
        ...

    def used_artifacts(self) -> Optional[Iterable[wandb.Artifact]]:
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
    def collect_runs(self) -> Iterable[ImporterRun]:
        ...

    def collect_reports(self) -> Iterable[wr.Report]:
        ...

    def import_run(self, run: ImporterRun):
        ...

    def import_report(self, report: wr.Report) -> None:
        ...


def _make_run_record(run: ImporterRun, interface: InterfaceQueue) -> pb.Record:
    _run = pb.RunRecord()
    _run.run_id = run.run_id()
    _run.entity = run.entity()
    _run.project = run.project()
    _run.display_name = coalesce(run.display_name())
    _run.notes = coalesce(run.notes(), "")
    _run.tags.extend(coalesce(run.tags(), []))
    _run.start_time.FromMilliseconds(run.start_time())

    host = run.host()
    if host is not None:
        _run.host = host

    runtime = run.runtime()
    if runtime is not None:
        _run.runtime = run.runtime()

    run_group = run.run_group()
    if run_group is not None:
        _run.run_group = run_group

    config = run.config()
    if "_wandb" not in config:
        config["_wandb"] = {}

    # how do I get this automatically?
    config["_wandb"]["code_path"] = run.code_path()
    config["_wandb"]["python_version"] = run.python_version()
    config["_wandb"]["cli_version"] = run.cli_version()

    interface._make_config(
        data=config,
        obj=_run.config,
    )  # is there a better way?
    return interface._make_record(run=_run)


def _make_output_record(run: ImporterRun, interface: InterfaceQueue, line) -> pb.Record:
    output_raw = pb.OutputRawRecord()
    output_raw.output_type = pb.OutputRawRecord.OutputType.STDOUT
    output_raw.line = line
    return interface._make_record(output_raw=output_raw)


def _make_summary_record(run: ImporterRun, interface: InterfaceQueue) -> pb.Record:
    d: dict = {
        **run.summary(),
        "_runtime": run.runtime(),  # quirk of runtime -- it has to be here!
        # '_timestamp': run.start_time()/1000,
    }
    d = cast_dictlike_to_dict(d)
    summary = interface._make_summary_from_dict(d)
    return interface._make_record(summary=summary)


def _make_history_records(
    run: ImporterRun, interface: InterfaceQueue
) -> Iterable[pb.Record]:
    for _, metrics in enumerate(run.metrics()):
        history = pb.HistoryRecord()
        for k, v in metrics.items():
            item = history.item.add()
            item.key = k
            item.value_json = json.dumps(v)
        yield interface._make_record(history=history)


def _make_files_record(
    run: ImporterRun, files_dict, interface: InterfaceQueue
) -> pb.Record:
    # when making the metadata file, it captures most things correctly
    # but notably it doesn't capture the start time!
    files_record = pb.FilesRecord()
    for path, policy in files_dict["files"]:
        f = files_record.files.add()
        f.path = path
        f.policy = file_policy_to_enum(policy)  # is this always "end"?
    return interface._make_record(files=files_record)


def _make_metadata_files_record(
    run: ImporterRun, interface: InterfaceQueue
) -> pb.Record:
    run_dir = f"./wandb-importer/{run.run_id()}"
    _make_metadata_file(run, run_dir)
    files = [(f"{run_dir}/files/wandb-metadata.json", "end")]

    return _make_files_record(run, {"files": files}, interface)


def _make_artifact_record(
    run: ImporterRun, interface: InterfaceQueue, artifact, use_artifact=False
) -> pb.Record:
    proto = interface._make_artifact(artifact)
    proto.run_id = run.run_id()
    proto.project = run.project()
    proto.entity = run.entity()
    proto.user_created = use_artifact
    proto.use_after_commit = use_artifact
    proto.finalize = True
    for tag in ["latest", "imported"]:
        proto.aliases.append(tag)
    return interface._make_record(artifact=proto)


def _make_telem_record(run: ImporterRun, interface: InterfaceQueue) -> pb.Record:
    telem = telem_pb.TelemetryRecord()

    feature = telem_pb.Feature()
    feature.importer_mlflow = True
    telem.feature.CopyFrom(feature)

    cli_version = run.cli_version()
    if cli_version:
        telem.cli_version = cli_version

    python_version = run.python_version()
    if python_version:
        telem.python_version = python_version

    return interface._make_record(telemetry=telem)


def _make_metadata_file(run: ImporterRun, run_dir: str) -> None:
    missing_text = "This data was not captured"

    d = {}
    d["os"] = coalesce(run.os_version(), missing_text)
    d["python"] = coalesce(run.python_version(), missing_text)
    d["program"] = coalesce(run.program(), missing_text)
    d["cuda"] = coalesce(run.cuda_version(), missing_text)
    d["host"] = coalesce(run.host(), missing_text)
    d["username"] = coalesce(run.username(), missing_text)
    d["executable"] = coalesce(run.executable(), missing_text)

    gpus_used = run.gpus_used()
    if gpus_used is not None:
        d["gpu_devices"] = json.dumps(gpus_used)
        d["gpu_count"] = json.dumps(len(gpus_used))

    cpus_used = run.cpus_used()
    if cpus_used is not None:
        d["cpu_count"] = json.dumps(run.cpus_used())

    mem_used = run.memory_used()
    if mem_used is not None:
        d["memory"] = json.dumps({"total": run.memory_used()})

    with open(f"{run_dir}/files/wandb-metadata.json", "w") as f:
        f.write(json.dumps(d))


# @dataclass
# class RecordMaker:
#     run: ImporterRun
#     interface: InterfaceQueue


# rm = RecordMaker(run, interface)
# rm.make_run_record(...)


def send_run_with_send_manager(
    run: ImporterRun,
    overrides: Optional[Dict[str, Any]] = None,
    settings_override=None,
) -> None:
    # does this need to be here for pmap?
    if overrides:
        for k, v in overrides.items():
            # `lambda: v` won't work!
            # https://stackoverflow.com/questions/10802002/why-deepcopy-doesnt-create-new-references-to-lambda-function
            setattr(run, k, lambda v=v: v)

    interface = InterfaceQueue()
    run_dir = f"./wandb-importer/{run.run_id()}"

    with SendManager.setup(
        run_dir, resume=False, settings_override=settings_override
    ) as sm:
        wandb.termlog(">> Make run record")
        sm.send(_make_run_record(run, interface))

        wandb.termlog(">> Use Artifacts")
        used_artifacts = run.used_artifacts()
        if used_artifacts is not None:
            for artifact in tqdm(
                used_artifacts, desc="Used artifacts", unit="artifacts", leave=False
            ):
                sm.send(
                    _make_artifact_record(run, interface, artifact, use_artifact=True)
                )

        wandb.termlog(">> Log Artifacts")
        artifacts = run.artifacts()
        if artifacts is not None:
            for artifact in tqdm(
                artifacts, desc="Logged artifacts", unit="artifacts", leave=False
            ):
                sm.send(_make_artifact_record(run, interface, artifact))

        wandb.termlog(">> Log Metadata")
        sm.send(_make_metadata_files_record(run, interface))

        wandb.termlog(">> Log History")
        for history_record in tqdm(
            _make_history_records(run, interface),
            desc="History",
            unit="steps",
            leave=False,
        ):
            sm.send(history_record)

        wandb.termlog(">> Log Summary")
        sm.send(_make_summary_record(run, interface))

        wandb.termlog(">> Log Output")
        # if hasattr(run, "_logs"):
        #     lines = run._logs
        lines = run.logs()
        if lines is not None:
            for line in tqdm(lines, desc="Stdout", unit="lines", leave=False):
                sm.send(_make_output_record(run, interface, line))

        wandb.termlog(">> Log Telem")
        sm.send(_make_telem_record(run, interface))
