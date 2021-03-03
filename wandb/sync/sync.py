"""
sync.
"""

from __future__ import print_function

import datetime
import fnmatch
import os
import sys
import threading
import time

from six.moves import queue
from six.moves.urllib.parse import quote as url_quote
import wandb
from wandb.proto import wandb_internal_pb2  # type: ignore
from wandb.util import check_and_warn_old

# TODO: consolidate dynamic imports
PY3 = sys.version_info.major == 3 and sys.version_info.minor >= 6
if PY3:
    from wandb.sdk.interface import interface
    from wandb.sdk.internal import datastore
    from wandb.sdk.internal import sender
    from wandb.sdk.internal import settings_static
else:
    from wandb.sdk_py27.interface import interface
    from wandb.sdk_py27.internal import datastore
    from wandb.sdk_py27.internal import sender
    from wandb.sdk_py27.internal import settings_static

WANDB_SUFFIX = ".wandb"
SYNCED_SUFFIX = ".synced"


class _LocalRun(object):
    def __init__(self, path, synced=None):
        self.path = path
        self.synced = synced
        self.offline = os.path.basename(path).startswith("offline-")
        self.datetime = datetime.datetime.strptime(
            os.path.basename(path).split("run-")[1].split("-")[0], "%Y%m%d_%H%M%S"
        )

    def __str__(self):
        return self.path


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
        wandb._set_internal_process(disable=True)
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
                filtered_files = list(filter(lambda f: f.endswith(WANDB_SUFFIX), files))
                if check_and_warn_old(files) or len(filtered_files) != 1:
                    print("Skipping directory: {}".format(sync_item))
                    continue
                sync_item = os.path.join(sync_item, filtered_files[0])
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
                email=None,
                silent=None,
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
            if self._mark_synced and not self._view:
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
        self._mark_synced = mark_synced
        self._app_url = app_url
        self._view = view
        self._verbose = verbose

    def status(self):
        pass

    def add(self, p):
        self._sync_list.append(str(p))

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
        return not self._thread.is_alive()

    def poll(self):
        time.sleep(1)
        return False


def get_runs(
    include_offline=None,
    include_online=None,
    include_synced=None,
    include_unsynced=None,
    exclude_globs=None,
    include_globs=None,
):
    # TODO(jhr): grab dir info from settings
    base = "wandb"
    if os.path.exists(".wandb"):
        base = ".wandb"
    if not os.path.exists(base):
        return ()

    all_dirs = os.listdir(base)
    dirs = []
    if include_offline:
        dirs += filter(lambda d: d.startswith("offline-run-"), all_dirs)
    if include_online:
        dirs += filter(lambda d: d.startswith("run-"), all_dirs)
    # find run file in each dir
    fnames = []
    for d in dirs:
        paths = os.listdir(os.path.join(base, d))
        if exclude_globs:
            paths = set(paths)
            for g in exclude_globs:
                paths = paths - set(fnmatch.filter(paths, g))
            paths = list(paths)
        if include_globs:
            new_paths = set()
            for g in include_globs:
                new_paths = new_paths.union(fnmatch.filter(paths, g))
            paths = list(new_paths)
        for f in paths:
            if f.endswith(WANDB_SUFFIX):
                fnames.append(os.path.join(base, d, f))
    filtered = []
    for f in fnames:
        dname = os.path.dirname(f)
        # TODO(frz): online runs are assumed to be synced, verify from binary log.
        if os.path.exists("{}{}".format(f, SYNCED_SUFFIX)) or os.path.basename(
            dname
        ).startswith("run-"):
            if include_synced:
                filtered.append(_LocalRun(dname, True))
        else:
            if include_unsynced:
                filtered.append(_LocalRun(dname, False))
    return tuple(filtered)


def get_run_from_path(path):
    return _LocalRun(path)
