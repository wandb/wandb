from abc import ABC
from datetime import datetime
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

import wandb
from wandb.proto import wandb_internal_pb2  # type: ignore
from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.internal import sender
from wandb.util import mkdir_exists_ok
from yaspin import yaspin

import sys

if sys.version_info < (3, 9):
    from typing import Iterable
else:
    from collections.abc import Iterable


class AbstractRun(ABC):
    """AbstractRun is an absctract class that custom importers must inherit from"""

    def __init__(self):
        self._id = None

    def to_proto(
        self, entity: str, project: str, interface: InterfaceQueue
    ) -> wandb_internal_pb2.RunRecord:
        proto_run = wandb_internal_pb2.RunRecord()
        proto_run.project = project
        proto_run.entity = entity
        proto_run.run_id = self._run_id()
        if self.group() is not None:
            proto_run.run_group = self.group()
        if self.job_type() is not None:
            proto_run.job_type = self.job_type()
        if self.name() is not None:
            proto_run.display_name = self.name()
        if self.notes() is not None:
            proto_run.notes = self.notes()
        for tag in self.tags():
            proto_run.tags.append(tag)
        # TODO: this isn't doing anything currently :(
        if self.start_time() is not None:
            proto_run.start_time.FromSeconds(
                int(self.start_time().utcnow().timestamp())
            )
        if self.git_url() is not None:
            proto_run.git.remote_url = self.git_url()
        if self.git_commit() is not None:
            proto_run.git.last_commit = self.git_commit()
        interface._make_config(data=self.config(), obj=proto_run.config)
        return proto_run

    def _run_id(self) -> str:
        if self._id is None and self.id() is None:
            self._id = wandb.util.generate_id()
        else:
            self._id = self.id()
        return self._id

    def name(self) -> Optional[str]:
        pass

    def id(self) -> Optional[str]:
        pass

    def config(self) -> Dict:
        return {}

    def summary(self) -> Dict:
        return {}

    def start_time(self) -> Optional[datetime]:
        return datetime.now()

    def tags(self) -> List[str]:
        return []

    def program(self) -> Optional[str]:
        pass

    def git_url(self) -> Optional[str]:
        pass

    def git_commit(self) -> Optional[str]:
        pass

    def tensorboard_logdir(self) -> Optional[str]:
        pass

    def finish_time(self) -> Optional[datetime]:
        pass

    def notes(self) -> Optional[str]:
        pass

    def job_type(self) -> Optional[str]:
        pass

    def group(self) -> Optional[str]:
        pass

    def metrics(self) -> Iterable[Dict]:
        return []

    # TODO: Sweeps?

    def logged_artifacts(self) -> Iterable[Any]:
        return []

    def used_artifacts(self) -> Iterable[Any]:
        return []


class Importer(object):
    def __init__(self, entity: str, project: str):
        self.entity = entity
        self.project = project
        self._thread = None
        self._runs: List[AbstractRun] = []
        self._tmpdir = tempfile.TemporaryDirectory()

    def add(self, run: AbstractRun):
        self._runs.append(run)

    def process(self):
        runs = self._runs[:]
        uniq_runs = set([r._run_id() for r in runs])
        assert len(runs) == len(uniq_runs), "All run objects must have a unique id"
        with yaspin(
            text=f"Importing {len(runs)} runs to {self.entity}/{self.project}"
        ) as sp:
            for run in runs:
                run_dir = os.path.join(self._tmpdir.name, f"run-{run._run_id()}")
                files_dir = os.path.join(run_dir, "files")
                mkdir_exists_ok(files_dir)
                send_manager = sender.SendManager.setup(run_dir, run.program())

                # TODO: potentially setup a handler thread for media etc.
                interface = send_manager._interface
                run_proto = run.to_proto(self.entity, self.project, interface)

                record = interface._make_record(run=run_proto)
                send_manager.send_run(record, file_dir=files_dir)
                summary = interface._make_summary_from_dict(run.summary())
                # TODO: handle define_metric somehow?
                # TODO: pass run object so we can handle wandb types in the metrics
                step = 0
                metrics = {}
                for step, metrics in enumerate(run.metrics()):
                    interface.publish_history(metrics, metrics.get("_step", step))
                # TODO: is this necessary / correct?
                if step == 0:
                    if run.summary() == {}:
                        summary = metrics
                    if summary != {}:
                        interface.publish_history(summary, 0)
                # TODO: handle artifacts
                # TODO: handle tensorboard_logdir
                if summary != {}:
                    record = interface._make_record(summary=summary)
                    send_manager.send_summary(record)
                interface.publish_exit(0)

                while len(send_manager) > 0:
                    data = next(send_manager)
                    send_manager.send(data)
                send_manager.finish()
                self._runs.pop(0)
                time.sleep(1)
            sp.ok()
