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

WANDB_SUFFIX = ".wandb"
SYNCED_SUFFIX = ".synced"


class SyncThread(threading.Thread):
    def __init__(
        self,
        sync_list,
        project=None,
        entity=None,
        run_id=None,
        view=None,
        verbose=None,
        mark_synced=None,
        app_url=None,
    ):
        threading.Thread.__init__(self)
        # mark this process as internal
        wandb._IS_INTERNAL_PROCESS = True
        self._sync_list = sync_list
        self._project = project
        self._entity = entity
        self._run_id = run_id
        self._view = view
        self._verbose = verbose
        self._mark_synced = mark_synced
        self._app_url = app_url

    def run(self):
        for sync_item in self._sync_list:
            if os.path.isdir(sync_item):
                files = os.listdir(sync_item)
                files = list(filter(lambda f: f.endswith(WANDB_SUFFIX), files))
                if len(files) != 1:
                    print("Skipping directory: {}", format(sync_item))
                    continue
                sync_item = os.path.join(sync_item, files[0])
            dirname = os.path.dirname(sync_item)
            files_dir = os.path.join(dirname, "files")
            sd = dict(
                files_dir=files_dir,
                _start_time=0,
                git_remote=None,
                resume=None,
                program=None,
                ignore_globs=(),
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
                settings=settings,
                record_q=record_q,
                result_q=result_q,
                interface=publish_interface,
            )
            ds = datastore.DataStore()
            ds.open_for_scan(sync_item)

            # save exit for final send
            exit_pb = None
            shown = False

            while True:
                data = ds.scan_data()
                if data is None:
                    break
                pb = wandb_internal_pb2.Record()
                pb.ParseFromString(data)
                record_type = pb.WhichOneof("record_type")
                if self._view:
                    if self._verbose:
                        print("Record:", pb)
                    else:
                        print("Record:", record_type)
                    continue
                if record_type == "run":
                    if self._run_id:
                        pb.run.run_id = self._run_id
                    if self._project:
                        pb.run.project = self._project
                    if self._entity:
                        pb.run.entity = self._entity
                    pb.control.req_resp = True
                elif record_type == "exit":
                    exit_pb = pb
                    continue
                elif record_type == "final":
                    assert exit_pb, "final seen without exit"
                    pb = exit_pb
                    exit_pb = None
                sm.send(pb)
                # send any records that were added in previous send
                while not record_q.empty():
                    data = record_q.get(block=True)
                    sm.send(data)

                if pb.control.req_resp:
                    result = result_q.get(block=True)
                    result_type = result.WhichOneof("result_type")
                    if not shown and result_type == "run_result":
                        r = result.run_result.run
                        # TODO(jhr): hardcode until we have settings in sync
                        url = "{}/{}/{}/runs/{}".format(
                            self._app_url,
                            url_quote(r.entity),
                            url_quote(r.project),
                            url_quote(r.run_id),
                        )
                        print("Syncing: %s ..." % url, end="")
                        sys.stdout.flush()
                        shown = True
            sm.finish()
            if self._mark_synced:
                synced_file = "{}{}".format(sync_item, SYNCED_SUFFIX)
                with open(synced_file, "w"):
                    pass
            print("done.")


class SyncManager:
    def __init__(
        self,
        project=None,
        entity=None,
        run_id=None,
        exclude_globs=None,
        include_globs=None,
        include_offline=None,
        include_online=None,
        include_synced=None,
        mark_synced=None,
        app_url=None,
        view=None,
        verbose=None,
    ):
        self._sync_list = []
        self._thread = None
        self._project = project
        self._entity = entity
        self._run_id = run_id
        self._exclude_globs = exclude_globs
        self._include_globs = include_globs
        self._include_offline = include_offline
        self._include_online = include_online
        self._include_synced = include_synced
        self._mark_synced = mark_synced
        self._app_url = app_url
        self._view = view
        self._verbose = verbose

    def status(self):
        pass

    def add(self, p):
        self._sync_list.append(p)

    def list(self):
        # TODO(jhr): grab dir info from settings
        base = "wandb"
        if os.path.exists(".wandb"):
            base = ".wandb"
        if not os.path.exists(base):
            return ()

        all_dirs = os.listdir(base)
        dirs = []
        if self._include_offline:
            dirs += filter(lambda d: d.startswith("offline-run-"), all_dirs)
        if self._include_online:
            dirs += filter(lambda d: d.startswith("run-"), all_dirs)

        # find run file in each dir
        fnames = []
        for d in dirs:
            paths = os.listdir(os.path.join(base, d))
            if self._exclude_globs:
                paths = set(paths)
                for g in self._exclude_globs:
                    paths = paths - set(fnmatch.filter(paths, g))
                paths = list(paths)
            if self._include_globs:
                new_paths = set()
                for g in self._include_globs:
                    new_paths = new_paths.union(fnmatch.filter(paths, g))
                paths = list(new_paths)
            for f in paths:
                if f.endswith(WANDB_SUFFIX):
                    fnames.append(os.path.join(base, d, f))

        # filter out synced
        if not self._include_synced:
            filtered = []
            for f in fnames:
                if not os.path.exists("{}{}".format(f, SYNCED_SUFFIX)):
                    filtered.append(f)
            fnames = filtered

        # return dirnames
        dnames = tuple(os.path.dirname(f) for f in fnames)

        return dnames

    def start(self):
        # create a thread for each file?
        self._thread = SyncThread(
            sync_list=self._sync_list,
            project=self._project,
            entity=self._entity,
            run_id=self._run_id,
            view=self._view,
            verbose=self._verbose,
            mark_synced=self._mark_synced,
            app_url=self._app_url,
        )
        self._thread.start()

    def is_done(self):
        return not self._thread.isAlive()

    def poll(self):
        time.sleep(1)
        return False
