"""
sync.
"""

from __future__ import print_function

import os
import threading
import time

from six.moves import queue
import wandb
from wandb.internal import datastore
from wandb.internal import sender
from wandb.internal import settings_static
from wandb.proto import wandb_internal_pb2  # type: ignore


class SyncThread(threading.Thread):
    def __init__(self, sync_list):
        threading.Thread.__init__(self)
        # mark this process as internal
        wandb._IS_INTERNAL_PROCESS = True
        self._sync_list = sync_list

    def run(self):
        for sync_item in self._sync_list:
            dirname = os.path.dirname(sync_item)
            files_dir = os.path.join(dirname, "files")
            sd = dict(files_dir=files_dir,
                      _start_time=0,
                      )
            settings = settings_static.SettingsStatic(sd)
            resp_queue = queue.Queue()
            sm = sender.SendManager(settings=settings, resp_q=resp_queue)
            ds = datastore.DataStore()
            ds.open_for_scan(sync_item)
            while True:
                data = ds.scan_data()
                if data is None:
                    break
                pb = wandb_internal_pb2.Record()
                pb.ParseFromString(data)
                sm.send(pb)
                if pb.control.req_resp:
                    try:
                        _ = resp_queue.get(timeout=20)
                    except queue.Empty:
                        raise Exception("timeout?")
            sm.finish()


class SyncManager:
    def __init__(self):
        self._sync_list = []
        self._thread = None

    def status(self):
        pass

    def add(self, p):
        # print("adding", p)
        self._sync_list.append(p)

    def list(self):
        # TODO(jhr): grab dir info from settings
        base = os.path.join("wandb", "runs")
        dirs = os.listdir(base)
        dirs = [d for d in dirs if d.startswith("run-")]
        # find run file in each dir
        fnames = []
        for d in dirs:
            files = os.listdir(os.path.join(base, d))
            for f in files:
                if f.endswith(".wandb"):
                    fnames.append(os.path.join(base, d, f))
        return fnames

    def start(self):
        # create a thread for each file?
        self._thread = SyncThread(self._sync_list)
        self._thread.start()

    def is_done(self):
        return not self._thread.isAlive()

    def poll(self):
        time.sleep(1)
        return False
