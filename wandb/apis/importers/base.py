import json
from abc import ABC, abstractmethod
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from tqdm.auto import tqdm

import wandb
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.interface.interface import file_policy_to_enum
from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.internal.sender import SendManager


@dataclass
class GPU:
    name: str
    memory_total: int


Name = str
Path = str


def coalesce(*arg: Any) -> Any:
    """Return the first non-none value in the list of arguments.  Similar to ?? in C#"""
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


class Run:
    def __init__(self) -> None:
        self.MISSING_ENTITY = "default"
        self.MISSING_PROJECT = "default"
        self.MISSING_RUN_ID = wandb.util.generate_id()  # type: ignore
        self.interface = InterfaceQueue()
        # self._autogen_run_id = wandb.util.generate_id()
        self._run_id = None
        self._entity = None
        self._project = None
        self.run_dir = f"./testing/{self.run_id()}"

    def run_id(self) -> str:
        if not self._run_id:
            self._run_id = self.MISSING_RUN_ID
            wandb.termwarn(
                f"`run_id` not specified.  Auto-generating id: {self.MISSING_RUN_ID}"
            )
        return self._run_id

    def entity(self) -> str:
        if not self._entity:
            self._entity = self.MISSING_ENTITY
            wandb.termwarn(
                f"`entity` not specified.  Defaulting to: {self.MISSING_ENTITY}"
            )
        return self._entity

    def project(self) -> str:
        if not self._project:
            self._project = self.MISSING_PROJECT
            wandb.termwarn(
                f"`project` not specified.  Defaulting to: {self.MISSING_PROJECT}"
            )
        return self._project

    def config(self) -> Dict[str, Any]:
        return {}

    def summary(self) -> Dict[str, float]:
        return {}

    def metrics(self) -> List[Dict[str, float]]:
        """
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

    def run_group(self) -> str:
        ...

    def job_type(self) -> str:
        ...

    def display_name(self) -> str:
        return self.run_id()

    def notes(self) -> str:
        ...

    def tags(self) -> List[str]:
        ...

    def settings(self):  # not sure what this is
        ...

    def artifacts(self) -> Iterable[Tuple[Name, Path]]:
        ...

    def os_version(self) -> str:
        ...

    def python_version(self) -> str:
        ...

    def cuda_version(self) -> str:
        ...

    def program(self) -> str:
        ...

    def host(self) -> str:
        ...

    def username(self) -> str:
        ...

    def executable(self) -> str:
        ...

    def gpus_used(self) -> List[GPU]:
        ...

    def cpus_used(self) -> int:  # can we get the model?
        ...

    def memory_used(self) -> int:
        ...

    def runtime(self) -> int:
        ...

    def start_time(self) -> int:
        ...

    def make_run_record(self) -> pb.Record:
        run = pb.RunRecord()
        run.run_id = coalesce(self.run_id(), wandb.util.generate_id())  # type: ignore
        run.entity = coalesce(self.entity(), self.MISSING_ENTITY)
        run.project = coalesce(self.project(), self.MISSING_PROJECT)
        run.display_name = coalesce(self.display_name())
        run.notes = coalesce(self.notes(), "")
        run.tags.extend(coalesce(self.tags(), list()))
        # run.start_time.FromMilliseconds(self.start_time())
        # run.runtime = self.runtime()
        if self.run_group():
            run.run_group = self.run_group()
        self.interface._make_config(
            data=self.config(), obj=run.config
        )  # is there a better way?
        return self.interface._make_record(run=run)

    def make_summary_record(self) -> pb.Record:
        d = {
            **self.summary(),
            "_runtime": self.runtime(),  # quirk of runtime -- it has to be here!
            # '_timestamp': self.start_time()/1000,
        }
        summary = self.interface._make_summary_from_dict(d)
        return self.interface._make_record(summary=summary)

    def make_history_records(self) -> Iterable[pb.Record]:
        for _, metrics in enumerate(self.metrics()):
            history = pb.HistoryRecord()
            for k, v in metrics.items():
                item = history.item.add()
                item.key = k
                item.value_json = json.dumps(v)
            yield self.interface._make_record(history=history)

    def make_files_record(self, files_dict) -> pb.Record:
        # when making the metadata file, it captures most things correctly
        # but notably it doesn't capture the start time!
        files_record = pb.FilesRecord()
        for path, policy in files_dict["files"]:
            f = files_record.files.add()
            f.path = path
            f.policy = file_policy_to_enum(policy)  # is this always "end"?
        return self.interface._make_record(files=files_record)

    def make_metadata_files_record(self) -> pb.Record:
        self._make_metadata_file(self.run_dir)
        return self.make_files_record(
            {"files": [[f"{self.run_dir}/files/wandb-metadata.json", "end"]]}
        )

    def make_artifact_record(self) -> pb.Record:
        art = wandb.Artifact(self.display_name(), "imported-artifacts")
        for name, path in self.artifacts():
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

    def _make_metadata_file(self, run_dir: str) -> None:
        missing_text = "MLFlow did not capture this info."

        d = {}
        if self.os_version():
            d["os"] = self.os_version()
        else:
            d["os"] = missing_text

        if self.python_version():
            d["python"] = self.python_version()
        else:
            d["python"] = missing_text

        if self.program():
            d["program"] = self.program()
        else:
            d["program"] = missing_text

        if self.cuda_version():
            d["cuda"] = self.cuda_version()
        if self.host():
            d["host"] = self.host()
        if self.username():
            d["username"] = self.username()
        if self.executable():
            d["executable"] = self.executable()
        if self.gpus_used():
            d["gpu_devices"] = self.gpus_used()
            d["gpu_count"] = len(d["gpu_devices"])
        if self.cpus_used():
            d["cpu_count"] = self.cpus_used()
        if self.memory_used():
            d["memory"] = {"total": self.memory_used()}

        with open(f"{run_dir}/files/wandb-metadata.json", "w") as f:
            f.write(json.dumps(d))


class Importer(ABC):
    @abstractmethod
    def get_all_runs(self) -> Iterable[Run]:
        ...

    def send_everything(self, overrides: Optional[Dict[str, Any]] = None) -> None:
        for run in tqdm(self.get_all_runs(), desc="Sending runs"):
            self.send(run, overrides)

    def send_everything_parallel(
        self, overrides: Optional[Dict[str, Any]] = None, **pool_kwargs: Any
    ) -> None:
        runs = list(self.get_all_runs())
        with tqdm(total=len(runs)) as pbar:
            with ProcessPoolExecutor(**pool_kwargs) as exc:
                futures = {
                    exc.submit(self.send, run, overrides=overrides): run for run in runs
                }
                for _ in as_completed(futures):
                    pbar.update(1)

    def send(
        self,
        run: Run,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> None:
        # does this need to be here for pmap?
        import mlflow

        mlflow.set_tracking_uri("http://localhost:4040")
        if overrides:
            for k, v in overrides.items():
                # `lambda: v` won't work!
                # https://stackoverflow.com/questions/10802002/why-deepcopy-doesnt-create-new-references-to-lambda-function
                setattr(run, k, lambda v=v: v)
        self._send(run)

    def _send(self, run: Run) -> None:
        # path is not writeable otherwise?  Not sure why...
        # !mkdir {run.run_dir} && chmod -R 755 {run.run_dir}
        with send_manager(run.run_dir) as sm:
            sm.send(run.make_run_record())
            sm.send(run.make_summary_record())
            sm.send(run.make_metadata_files_record())
            for history_record in run.make_history_records():
                sm.send(history_record)
            if run.artifacts():
                sm.send(run.make_artifact_record())
