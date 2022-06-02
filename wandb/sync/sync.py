"""
sync.
"""

import datetime
import fnmatch
import os
import queue
import sys
import tempfile
import threading
import time
from urllib.parse import quote as url_quote

import wandb
from wandb.proto import wandb_internal_pb2  # type: ignore
from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.internal import datastore
from wandb.sdk.internal import handler
from wandb.sdk.internal import sender
from wandb.sdk.internal import tb_watcher
from wandb.util import check_and_warn_old, mkdir_exists_ok

WANDB_SUFFIX = ".wandb"
SYNCED_SUFFIX = ".synced"
TFEVENT_SUBSTRING = ".tfevents."
TMPDIR = tempfile.TemporaryDirectory()


class _LocalRun:
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
        sync_tensorboard=None,
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
        self._sync_tensorboard = sync_tensorboard

    def _parse_pb(self, data, exit_pb=None):
        pb = wandb_internal_pb2.Record()
        pb.ParseFromString(data)
        record_type = pb.WhichOneof("record_type")
        if self._view:
            if self._verbose:
                print("Record:", pb)
            else:
                print("Record:", record_type)
            return pb, exit_pb, True
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
            return pb, exit_pb, True
        elif record_type == "final":
            assert exit_pb, "final seen without exit"
            pb = exit_pb
            exit_pb = None
        return pb, exit_pb, False

    def _find_tfevent_files(self, sync_item):
        tb_event_files = 0
        tb_logdirs = []
        tb_root = None
        if self._sync_tensorboard:
            if os.path.isdir(sync_item):
                files = []
                for dirpath, _, _files in os.walk(sync_item):
                    for f in _files:
                        if TFEVENT_SUBSTRING in f:
                            files.append(os.path.join(dirpath, f))
                for tfevent in files:
                    tb_event_files += 1
                    tb_dir = os.path.dirname(os.path.abspath(tfevent))
                    if tb_dir not in tb_logdirs:
                        tb_logdirs.append(tb_dir)
                if len(tb_logdirs) > 0:
                    tb_root = os.path.dirname(os.path.commonprefix(tb_logdirs))

            elif TFEVENT_SUBSTRING in sync_item:
                tb_root = os.path.dirname(os.path.abspath(sync_item))
                tb_logdirs.append(tb_root)
                tb_event_files = 1
        return tb_event_files, tb_logdirs, tb_root

    def _setup_tensorboard(self, tb_root, tb_logdirs, tb_event_files, sync_item):
        """Returns true if this sync item can be synced as tensorboard"""
        if tb_root is not None:
            if tb_event_files > 0 and sync_item.endswith(WANDB_SUFFIX):
                wandb.termwarn("Found .wandb file, not streaming tensorboard metrics.")
            else:
                print(f"Found {tb_event_files} tfevent files in {tb_root}")
                if len(tb_logdirs) > 3:
                    wandb.termwarn(
                        "Found {} directories containing tfevent files. "
                        "If these represent multiple experiments, sync them "
                        "individually or pass a list of paths."
                    )
                return True
        return False

    def _send_tensorboard(self, tb_root, tb_logdirs, send_manager):
        if self._entity is None:
            viewer, server_info = send_manager._api.viewer_server_info()
            self._entity = viewer.get("entity")
        proto_run = wandb_internal_pb2.RunRecord()
        proto_run.run_id = self._run_id or wandb.util.generate_id()
        proto_run.project = self._project or wandb.util.auto_project_name(None)
        proto_run.entity = self._entity

        url = "{}/{}/{}/runs/{}".format(
            self._app_url,
            url_quote(proto_run.entity),
            url_quote(proto_run.project),
            url_quote(proto_run.run_id),
        )
        print("Syncing: %s ..." % url)
        sys.stdout.flush()
        # using a handler here automatically handles the step
        # logic, adds summaries to the run, and handles different
        # file types (like images)... but we need to remake the send_manager
        record_q = queue.Queue()
        sender_record_q = queue.Queue()
        new_interface = InterfaceQueue(record_q)
        send_manager = sender.SendManager(
            send_manager._settings, sender_record_q, queue.Queue(), new_interface
        )
        record = send_manager._interface._make_record(run=proto_run)
        settings = wandb.Settings(
            root_dir=TMPDIR.name,
            run_id=proto_run.run_id,
            _start_datetime=datetime.datetime.now(),
            _start_time=time.time(),
        )

        handle_manager = handler.HandleManager(
            settings, record_q, None, False, sender_record_q, None, new_interface
        )

        mkdir_exists_ok(settings.files_dir)
        send_manager.send_run(record, file_dir=settings.files_dir)
        watcher = tb_watcher.TBWatcher(settings, proto_run, new_interface, True)

        for tb in tb_logdirs:
            watcher.add(tb, True, tb_root)
            sys.stdout.flush()
        watcher.finish()

        # send all of our records like a boss
        progress_step = 0
        spinner_states = ["-", "\\", "|", "/"]
        line = " Uploading data to wandb\r"
        while len(handle_manager) > 0:
            data = next(handle_manager)
            handle_manager.handle(data)
            while len(send_manager) > 0:
                data = next(send_manager)
                send_manager.send(data)

            print_line = spinner_states[progress_step % 4] + line
            wandb.termlog(print_line, newline=False, prefix=True)
            progress_step += 1

        # finish sending any data
        while len(send_manager) > 0:
            data = next(send_manager)
            send_manager.send(data)
        sys.stdout.flush()
        handle_manager.finish()
        send_manager.finish()

    def _robust_scan(self, ds):
        """Attempt to scan data, handling incomplete files"""
        try:
            return ds.scan_data()
        except AssertionError as e:
            if ds.in_last_block():
                wandb.termwarn(
                    ".wandb file is incomplete ({}), be sure to sync this run again once it's finished".format(
                        e
                    )
                )
                return None
            else:
                raise e

    def run(self):
        for sync_item in self._sync_list:
            tb_event_files, tb_logdirs, tb_root = self._find_tfevent_files(sync_item)
            if os.path.isdir(sync_item):
                files = os.listdir(sync_item)
                filtered_files = list(filter(lambda f: f.endswith(WANDB_SUFFIX), files))
                if tb_root is None and (
                    check_and_warn_old(files) or len(filtered_files) != 1
                ):
                    print(f"Skipping directory: {sync_item}")
                    continue
                if len(filtered_files) > 0:
                    sync_item = os.path.join(sync_item, filtered_files[0])
            sync_tb = self._setup_tensorboard(
                tb_root, tb_logdirs, tb_event_files, sync_item
            )
            # If we're syncing tensorboard, let's use a tmp dir for images etc.
            root_dir = TMPDIR.name if sync_tb else os.path.dirname(sync_item)
            sm = sender.SendManager.setup(root_dir)
            if sync_tb:
                self._send_tensorboard(tb_root, tb_logdirs, sm)
                continue

            ds = datastore.DataStore()
            try:
                ds.open_for_scan(sync_item)
            except AssertionError as e:
                print(f".wandb file is empty ({e}), skipping: {sync_item}")
                continue

            # save exit for final send
            exit_pb = None
            finished = False
            shown = False
            while True:
                data = self._robust_scan(ds)
                if data is None:
                    break
                pb, exit_pb, cont = self._parse_pb(data, exit_pb)
                if exit_pb is not None:
                    finished = True
                if cont:
                    continue
                sm.send(pb)
                # send any records that were added in previous send
                while not sm._record_q.empty():
                    data = sm._record_q.get(block=True)
                    sm.send(data)

                if pb.control.req_resp:
                    result = sm._result_q.get(block=True)
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
            # Only mark synced if the run actually finished
            if self._mark_synced and not self._view and finished:
                synced_file = f"{sync_item}{SYNCED_SUFFIX}"
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
        sync_tensorboard=None,
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
        self._sync_tensorboard = sync_tensorboard

    def status(self):
        pass

    def add(self, p):
        self._sync_list.append(os.path.abspath(str(p)))

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
            sync_tensorboard=self._sync_tensorboard,
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
        dirs += filter(lambda _d: _d.startswith("offline-run-"), all_dirs)
    if include_online:
        dirs += filter(lambda _d: _d.startswith("run-"), all_dirs)
    # find run file in each dir
    fnames = []
    dirs.sort()
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
        if os.path.exists(f"{f}{SYNCED_SUFFIX}") or os.path.basename(dname).startswith(
            "run-"
        ):
            if include_synced:
                filtered.append(_LocalRun(dname, True))
        else:
            if include_unsynced:
                filtered.append(_LocalRun(dname, False))
    return tuple(filtered)


def get_run_from_path(path):
    return _LocalRun(path)
