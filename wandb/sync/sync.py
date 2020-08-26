"""
sync.
"""

from __future__ import print_function

import fnmatch
import os
import sys
import threading
import time

from six.moves import queue
from six.moves.urllib.parse import quote as url_quote
import wandb
from wandb.interface import interface
from wandb.internal import datastore
from wandb.internal import sender
from wandb.internal import settings_static
from wandb.proto import wandb_internal_pb2  # type: ignore


class SyncThread(threading.Thread):
    def __init__(self, sync_list, project=None, entity=None, run_id=None):
        threading.Thread.__init__(self)
        # mark this process as internal
        wandb._IS_INTERNAL_PROCESS = True
        self._sync_list = sync_list
        self._project = project
        self._entity = entity
        self._run_id = run_id

    def run(self):
        for sync_item in self._sync_list:
            dirname = os.path.dirname(sync_item)
            files_dir = os.path.join(dirname, "files")
            sd = dict(files_dir=files_dir,
                      _start_time=0,
                      git_remote=None,
                      resume=None,
                      program=None,
                      ignore_globs=[],
                      run_id=None,
                      entity=None,
                      project=None,
                      run_group=None,
                      job_type=None,
                      run_tags=None,
                      run_name=None,
                      run_notes=None,
                      save_code=None,
                      )
            settings = settings_static.SettingsStatic(sd)
            record_q = queue.Queue()
            result_q = queue.Queue()
            publish_interface = interface.BackendSender(record_q=record_q)
            sm = sender.SendManager(
                settings=settings, record_q=record_q, result_q=result_q,
                interface=publish_interface)
            ds = datastore.DataStore()
            ds.open_for_scan(sync_item)
            while True:
                data = ds.scan_data()
                if data is None:
                    break
                pb = wandb_internal_pb2.Record()
                pb.ParseFromString(data)
                record_type = pb.WhichOneof("record_type")
                if record_type == "run":
                    if self._run_id:
                        pb.run.run_id = self._run_id
                    if self._project:
                        pb.run.project = self._project
                    if self._entity:
                        pb.run.entity = self._entity
                    pb.control.req_resp = True
                sm.send(pb)
                while not record_q.empty():
                    data = record_q.get(block=True)
                    sm.send(data)
                if pb.control.req_resp:
                    result = result_q.get(block=True)
                    result_type = result.WhichOneof("result_type")
                    if result_type == "run_result":
                        r = result.run_result.run
                        # TODO(jhr): hardcode until we have settings in sync
                        app_url = "https://app.wandb.ai"
                        url = "{}/{}/{}/runs/{}".format(
                            app_url,
                            url_quote(r.entity),
                            url_quote(r.project),
                            url_quote(r.run_id)
                        )
                        print("Syncing: %s ..." % url, end="")
                        sys.stdout.flush()
            sm.finish()
            print("done.")


class SyncManager:
    def __init__(self, project=None, entity=None, run_id=None, ignore=None):
        self._sync_list = []
        self._thread = None
        self._project = project
        self._entity = entity
        self._run_id = run_id
        self._ignore = ignore

    def status(self):
        pass

    def add(self, p):
        # print("adding", p)
        self._sync_list.append(p)

    def list(self):
        # TODO(jhr): grab dir info from settings
        base = os.path.join("wandb")
        dirs = os.listdir(base)
        dirs = [d for d in dirs if d.startswith("offline-run-")]
        # find run file in each dir
        fnames = []
        for d in dirs:
            paths = os.listdir(os.path.join(base, d))
            if self._ignore:
                paths = set(paths)
                for g in self._ignore:
                    paths = paths - set(fnmatch.filter(paths, g))
                paths = list(paths)

            for f in paths:
                if f.endswith(".wandb"):
                    fnames.append(os.path.join(base, d, f))
        return fnames

    def start(self):
        # create a thread for each file?
        self._thread = SyncThread(
            self._sync_list,
            project=self._project,
            entity=self._entity,
            run_id=self._run_id)
        self._thread.start()

    def is_done(self):
        return not self._thread.isAlive()

    def poll(self):
        time.sleep(1)
        return False
