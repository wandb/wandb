import json
import platform
from abc import ABC, abstractmethod
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional, Tuple

from tqdm.auto import tqdm

import wandb
from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_telemetry_pb2 as telem_pb
from wandb.sdk.interface.interface import file_policy_to_enum
from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.internal.sender import SendManager

Name = str
Path = str


def coalesce(*arg: Any) -> Any:
    """Return the first non-none value in the list of arguments.  Similar to ?? in C#."""
    return next((a for a in arg if a is not None), None)


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

    def artifacts(self) -> Optional[Iterable[Tuple[Name, Path]]]:
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
        run.display_name = coalesce(self.display_name())
        run.notes = coalesce(self.notes(), "")
        run.tags.extend(coalesce(self.tags(), list()))
        # run.start_time.FromMilliseconds(self.start_time())
        # run.runtime = self.runtime()
        run_group = self.run_group()
        if run_group is not None:
            run.run_group = run_group
        self.interface._make_config(
            data=self.config(),
            obj=run.config,
        )  # is there a better way?
        return self.interface._make_record(run=run)

    def _make_summary_record(self) -> pb.Record:
        d: dict = {
            **self.summary(),
            "_runtime": self.runtime(),  # quirk of runtime -- it has to be here!
            # '_timestamp': self.start_time()/1000,
        }
        summary = self.interface._make_summary_from_dict(d)
        return self.interface._make_record(summary=summary)

    def _make_history_records(self) -> Iterable[pb.Record]:
        for _, metrics in enumerate(self.metrics()):
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
        self._make_metadata_file(self.run_dir)
        return self._make_files_record(
            {"files": [[f"{self.run_dir}/files/wandb-metadata.json", "end"]]}
        )

    def _make_artifact_record(self) -> pb.Record:
        art = wandb.Artifact(self.display_name(), "imported-artifacts")
        artifacts = self.artifacts()
        if artifacts is not None:
            for name, path in artifacts:
                art.add_file(path, name)
        proto = self.interface._make_artifact(art)
        proto.run_id = self.run_id()
        proto.project = self.project()
        proto.entity = self.entity()
        proto.user_created = False
        proto.use_after_commit = False
        proto.finalize = True
        for tag in ["latest", "imported"]:
            proto.aliases.append(tag)
        return self.interface._make_record(artifact=proto)

    def _make_telem_record(self) -> pb.Record:
        feature = telem_pb.Feature()
        feature.importer_mlflow = True

        telem = telem_pb.TelemetryRecord()
        telem.feature.CopyFrom(feature)
        telem.python_version = platform.python_version()  # importer's python version
        telem.cli_version = wandb.__version__
        return self.interface._make_record(telemetry=telem)

    def _make_metadata_file(self, run_dir: str) -> None:
        missing_text = "MLFlow did not capture this info."

        d = {}
        if self.os_version() is not None:
            d["os"] = self.os_version()
        else:
            d["os"] = missing_text

        if self.python_version() is not None:
            d["python"] = self.python_version()
        else:
            d["python"] = missing_text

        if self.program() is not None:
            d["program"] = self.program()
        else:
            d["program"] = missing_text

        if self.cuda_version() is not None:
            d["cuda"] = self.cuda_version()
        if self.host() is not None:
            d["host"] = self.host()
        if self.username() is not None:
            d["username"] = self.username()
        if self.executable() is not None:
            d["executable"] = self.executable()
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


class Importer(ABC):
    @abstractmethod
    def download_all_runs(self) -> Iterable[ImporterRun]:
        ...

    def import_all(self, overrides: Optional[Dict[str, Any]] = None) -> None:
        for run in tqdm(self.download_all_runs(), desc="Sending runs"):
            self.import_one(run, overrides)

    def import_all_parallel(
        self, overrides: Optional[Dict[str, Any]] = None, **pool_kwargs: Any
    ) -> None:
        runs = list(self.download_all_runs())
        with tqdm(total=len(runs)) as pbar:
            with ProcessPoolExecutor(**pool_kwargs) as exc:
                futures = {
                    exc.submit(self.import_one, run, overrides=overrides): run
                    for run in runs
                }
                for future in as_completed(futures):
                    run = futures[future]
                    pbar.update(1)
                    pbar.set_description(
                        f"Imported Run: {run.run_group()} {run.display_name()}"
                    )

    def import_one(
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
        self._import_one(run)

    def _import_one(self, run: ImporterRun) -> None:
        with send_manager(run.run_dir) as sm:
            sm.send(run._make_run_record())
            sm.send(run._make_summary_record())
            sm.send(run._make_metadata_files_record())
            for history_record in run._make_history_records():
                sm.send(history_record)
            if run.artifacts() is not None:
                sm.send(run._make_artifact_record())
            sm.send(run._make_telem_record())
