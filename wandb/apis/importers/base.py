import json
import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional
from unittest.mock import patch

from tqdm import tqdm

import wandb
from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_telemetry_pb2 as telem_pb
from wandb.sdk.interface.interface import file_policy_to_enum
from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.internal.sender import SendManager
from wandb.util import coalesce

with patch("click.echo"):
    import wandb.apis.reports as wr

Name = str
Path = str


@contextmanager
def send_manager(root_dir):
    sm = SendManager.setup(root_dir, resume=False)
    try:
        yield sm
    finally:
        # flush any remaining records
        while sm:
            data = next(sm)
            sm.send(data)
        sm.finish()


class ImporterRun:
    def __init__(self) -> None:
        self.interface = InterfaceQueue()
        self.run_dir = f"./wandb-importer/{self.run_id()}"
        try:
            self._metrics = self.metrics()
        except Exception as e:
            print("problem", e)
            self._metrics = []
        self._artifacts = self.artifacts()
        self._used_artifacts = self.used_artifacts()

    def run_id(self) -> str:
        _id = wandb.util.generate_id()
        wandb.termwarn(f"`run_id` not specified.  Autogenerating id: {_id}")
        return _id

    def entity(self) -> str:
        _entity = "unspecified-entity"
        wandb.termwarn(f"`entity` not specified.  Defaulting to: {_entity}")
        return _entity

    def project(self) -> str:
        _project = "unspecified-project"
        wandb.termwarn(f"`project` not specified.  Defaulting to: {_project}")
        return _project

    def config(self) -> Dict[str, Any]:
        return {}

    def summary(self) -> Dict[str, float]:
        return {}

    def metrics(self) -> List[Dict[str, float]]:
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
        return []

    def run_group(self) -> Optional[str]:
        ...

    def job_type(self) -> Optional[str]:
        ...

    def display_name(self) -> str:
        return self.run_id()

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

    def _make_run_record(self) -> pb.Record:
        run = pb.RunRecord()
        run.run_id = self.run_id()
        run.entity = self.entity()
        run.project = self.project()
        host = self.host()
        if host:
            run.host = host
        run.display_name = coalesce(self.display_name())
        run.notes = coalesce(self.notes(), "")
        run.tags.extend(coalesce(self.tags(), []))

        # start_time = 1400000
        start_time = self.start_time()
        run.start_time.FromMilliseconds(start_time)
        # config["_wandb"]["start_time"] = start_time

        runtime = self.runtime()
        if runtime:
            run.runtime = self.runtime()

        run_group = self.run_group()
        if run_group is not None:
            run.run_group = run_group

        config = self.config()
        if "_wandb" not in config:
            config["_wandb"] = {}

        # how do I get this automatically?
        config["_wandb"]["code_path"] = self.code_path()
        config["_wandb"]["python_version"] = self.python_version()
        config["_wandb"]["cli_version"] = self.cli_version()

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
            **self.summary(),
            "_runtime": self.runtime(),  # quirk of runtime -- it has to be here!
            # '_timestamp': self.start_time()/1000,
        }
        d = cast_dictlike_to_dict(d)
        summary = self.interface._make_summary_from_dict(d)
        return self.interface._make_record(summary=summary)

    def _make_history_records(self) -> Iterable[pb.Record]:
        for _, metrics in enumerate(self._metrics):
            history = pb.HistoryRecord()
            for k, v in metrics.items():
                item = history.item.add()
                item.key = k
                item.value_json = json.dumps(v)
            yield self.interface._make_record(history=history)

    def _make_files_record(self, files_dict) -> pb.Record:
        # when making the metadata file, it captures most things correctly
        # but notably it doesn't capture the start time!
        files_record = pb.FilesRecord()
        for path, policy in files_dict["files"]:
            f = files_record.files.add()
            f.path = path
            f.policy = file_policy_to_enum(policy)  # is this always "end"?
        return self.interface._make_record(files=files_record)

    def _make_metadata_files_record(self) -> pb.Record:
        # self._make_metadata_file(self.run_dir)
        # files = [(f"{self.run_dir}/files/wandb-metadata.json", "end")]
        files = self._files

        return self._make_files_record({"files": files})

    def _make_artifact_record(self, artifact, use_artifact=False) -> pb.Record:
        proto = self.interface._make_artifact(artifact)
        proto.run_id = self.run_id()
        proto.project = self.project()
        proto.entity = self.entity()
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

        telem.cli_version = self.cli_version()
        telem.python_version = self.python_version()

        return self.interface._make_record(telemetry=telem)

    def _make_metadata_file(self, run_dir: str) -> None:
        missing_text = "This data was not captured"

        d = {}
        d["os"] = coalesce(self.os_version(), missing_text)
        d["python"] = coalesce(self.python_version(), missing_text)
        d["program"] = coalesce(self.program(), missing_text)
        d["cuda"] = coalesce(self.cuda_version(), missing_text)
        d["host"] = coalesce(self.host(), missing_text)
        d["username"] = coalesce(self.username(), missing_text)
        d["executable"] = coalesce(self.executable(), missing_text)

        gpus_used = self.gpus_used()
        if gpus_used is not None:
            d["gpu_devices"] = json.dumps(gpus_used)
            d["gpu_count"] = json.dumps(len(gpus_used))

        cpus_used = self.cpus_used()
        if cpus_used is not None:
            d["cpu_count"] = json.dumps(self.cpus_used())

        mem_used = self.memory_used()
        if mem_used is not None:
            d["memory"] = json.dumps({"total": self.memory_used()})

        with open(f"{run_dir}/files/wandb-metadata.json", "w") as f:
            f.write(json.dumps(d))

    @staticmethod
    def _handle_incompatible_strings(s):
        valid_chars = r"[^a-zA-Z0-9_\-\.]"
        replacement = "__"

        return re.sub(valid_chars, replacement, s)


class Importer:
    def download_all_runs(self) -> Iterable[ImporterRun]:
        raise NotImplementedError

    def download_all_reports(self) -> Iterable[wr.Report]:
        raise NotImplementedError

    def import_one_report(self, report) -> None:
        raise NotImplementedError

    def import_all_reports(self, limit=10) -> None:
        raise NotImplementedError

    def import_all_runs(
        self, overrides: Optional[Dict[str, Any]] = None, **pool_kwargs: Any
    ) -> None:
        runs = list(self.download_all_runs())
        with tqdm(total=len(runs)) as pbar:
            with ProcessPoolExecutor(**pool_kwargs) as exc:
                futures = {
                    exc.submit(self.import_one_run, run, overrides=overrides): run
                    for run in runs
                }
                for future in as_completed(futures):
                    run = futures[future]
                    try:
                        future.result()
                    except Exception as exc:
                        wandb.termerror(f"Failed to import {run.display_name()}: {exc}")
                    else:
                        pbar.set_description(
                            f"Imported Run: {run.run_group()} {run.display_name()}"
                        )
                    finally:
                        pbar.update(1)

    def import_one_run(
        self,
        run: ImporterRun,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> None:
        # does this need to be here for pmap?
        if overrides:
            for k, v in overrides.items():
                # `lambda: v` won't work!
                # https://stackoverflow.com/questions/10802002/why-deepcopy-doesnt-create-new-references-to-lambda-function
                setattr(run, k, lambda v=v: v)
        self._import_one_run(run)

    def _import_one_run(self, run: ImporterRun) -> None:
        with send_manager(run.run_dir) as sm:
            wandb.termlog(">> Make run record")
            sm.send(run._make_run_record())

            wandb.termlog(">> Use Artifacts")
            used_artifacts = run._used_artifacts
            if used_artifacts is not None:
                for artifact in used_artifacts:
                    sm.send(run._make_artifact_record(artifact, use_artifact=True))

            wandb.termlog(">> Log Artifacts")
            artifacts = run._artifacts
            if artifacts is not None:
                for artifact in artifacts:
                    sm.send(run._make_artifact_record(artifact))

            wandb.termlog(">> Log Metadata")
            sm.send(run._make_metadata_files_record())

            # wandb.termlog(">> Log History")
            # for history_record in run._make_history_records():
            #     sm.send(history_record)

            wandb.termlog(">> Log Summary")
            sm.send(run._make_summary_record())

            wandb.termlog(">> Log Output")
            lines = run._logs
            if lines is not None:
                for line in lines:
                    sm.send(run._make_output_record(line))

            wandb.termlog(">> Log Telem")
            sm.send(run._make_telem_record())


def cast_dictlike_to_dict(d):
    for k, v in d.items():
        if isinstance(v, dict):
            cast_dictlike_to_dict(v)
        elif hasattr(v, "keys"):
            d[k] = dict(v)
            cast_dictlike_to_dict(d[k])
    return d
