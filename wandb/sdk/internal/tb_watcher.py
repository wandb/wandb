#
"""
tensor b watcher.
"""

import logging
import os
import socket
import sys
import threading
import time

import six
from six.moves import queue
import wandb
from wandb import util
from wandb.viz import custom_chart_panel_config, CustomChart

from . import run as internal_run

if wandb.TYPE_CHECKING:
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from ..interface.interface import BackendSender
        from .settings_static import SettingsStatic
        from typing import Dict, List, Optional
        from wandb.proto.wandb_internal_pb2 import RunRecord
        from six.moves.queue import PriorityQueue
        from tensorboard.compat.proto.event_pb2 import ProtoEvent
        from tensorboard.backend.event_processing.event_file_loader import (
            EventFileLoader,
        )

        HistoryDict = Dict[str, object]

# Give some time for tensorboard data to be flushed
SHUTDOWN_DELAY = 5
ERROR_DELAY = 5
REMOTE_FILE_TOKEN = "://"
logger = logging.getLogger(__name__)


def _link_and_save_file(
    path: str, base_path: str, interface: "BackendSender", settings: "SettingsStatic"
) -> None:
    # TODO(jhr): should this logic be merged with Run.save()
    files_dir = settings.files_dir
    file_name = os.path.relpath(path, base_path)
    abs_path = os.path.abspath(path)
    wandb_path = os.path.join(files_dir, file_name)
    util.mkdir_exists_ok(os.path.dirname(wandb_path))
    # We overwrite existing symlinks because namespaces can change in Tensorboard
    if os.path.islink(wandb_path) and abs_path != os.readlink(wandb_path):
        os.remove(wandb_path)
        os.symlink(abs_path, wandb_path)
    elif not os.path.exists(wandb_path):
        os.symlink(abs_path, wandb_path)
    # TODO(jhr): need to figure out policy, live/throttled?
    interface.publish_files(dict(files=[(file_name, "live")]))


def is_tfevents_file_created_by(path: str, hostname: str, start_time: float) -> bool:
    """Checks if a path is a tfevents file created by hostname.

    tensorboard tfevents filename format:
        https://github.com/tensorflow/tensorboard/blob/f3f26b46981da5bd46a5bb93fcf02d9eb7608bc1/tensorboard/summary/writer/event_file_writer.py#L81
    tensorflow tfevents fielname format:
        https://github.com/tensorflow/tensorflow/blob/8f597046dc30c14b5413813d02c0e0aed399c177/tensorflow/core/util/events_writer.cc#L68
    """
    if not path:
        raise ValueError("Path must be a nonempty string")
    basename = os.path.basename(path)
    if basename.endswith(".profile-empty"):
        return False
    fname_components = basename.split(".")
    try:
        tfevents_idx = fname_components.index("tfevents")
    except ValueError:
        return False
    # check the hostname, which may have dots
    for i, part in enumerate(hostname.split(".")):
        try:
            fname_component_part = fname_components[tfevents_idx + 2 + i]
        except IndexError:
            return False
        if part != fname_component_part:
            return False
    try:
        created_time = int(fname_components[tfevents_idx + 1])
    except (ValueError, IndexError):
        return False
    # Ensure that the file is newer then our start time, and that it was
    # created from the same hostname.
    # TODO: we should also check the PID (also contained in the tfevents
    #     filename). Can we assume that our parent pid is the user process
    #     that wrote these files?
    return created_time >= int(start_time)  # noqa: W503


class TBWatcher(object):
    _logdirs: "Dict[str, TBDirWatcher]"
    _watcher_queue: "PriorityQueue"

    def __init__(
        self,
        settings: "SettingsStatic",
        run_proto: "RunRecord",
        interface: "BackendSender",
        force: bool = False,
    ) -> None:
        self._logdirs = {}
        self._consumer = None
        self._settings = settings
        self._interface = interface
        self._run_proto = run_proto
        self._force = force
        # TODO(jhr): do we need locking in this queue?
        self._watcher_queue = queue.PriorityQueue()
        wandb.tensorboard.reset_state()

    def _calculate_namespace(self, logdir: str, rootdir: str) -> "Optional[str]":
        namespace: "Optional[str]"
        dirs = list(self._logdirs) + [logdir]

        if os.path.isfile(logdir):
            filename = os.path.basename(logdir)
        else:
            filename = ""

        if rootdir == "":
            rootdir = util.to_forward_slash_path(
                os.path.dirname(os.path.commonprefix(dirs))
            )
            # Tensorboard loads all tfevents files in a directory and prepends
            # their values with the path. Passing namespace to log allows us
            # to nest the values in wandb
            # Note that we strip '/' instead of os.sep, because elsewhere we've
            # converted paths to forward slash.
            namespace = logdir.replace(filename, "").replace(rootdir, "").strip("/")
            # TODO: revisit this heuristic, it exists because we don't know the
            # root log directory until more than one tfevents file is written to
            if len(dirs) == 1 and namespace not in ["train", "validation"]:
                namespace = None
        else:
            namespace = logdir.replace(filename, "").replace(rootdir, "").strip("/")

        return namespace

    def add(self, logdir: str, save: bool, root_dir: str) -> None:
        logdir = util.to_forward_slash_path(logdir)
        root_dir = util.to_forward_slash_path(root_dir)
        if logdir in self._logdirs:
            return
        namespace = self._calculate_namespace(logdir, root_dir)
        # TODO(jhr): implement the deferred tbdirwatcher to find namespace

        if not self._consumer:
            self._consumer = TBEventConsumer(
                self, self._watcher_queue, self._run_proto, self._settings
            )
            self._consumer.start()

        tbdir_watcher = TBDirWatcher(
            self, logdir, save, namespace, self._watcher_queue, self._force
        )
        self._logdirs[logdir] = tbdir_watcher
        tbdir_watcher.start()

    def finish(self) -> None:
        for tbdirwatcher in six.itervalues(self._logdirs):
            tbdirwatcher.shutdown()
        for tbdirwatcher in six.itervalues(self._logdirs):
            tbdirwatcher.finish()
        if self._consumer:
            self._consumer.finish()


class TBDirWatcher(object):
    def __init__(
        self,
        tbwatcher: "TBWatcher",
        logdir: str,
        save: bool,
        namespace: "Optional[str]",
        queue: "PriorityQueue",
        force: bool = False,
    ) -> None:
        self.directory_watcher = util.get_module(
            "tensorboard.backend.event_processing.directory_watcher",
            required="Please install tensorboard package",
        )
        # self.event_file_loader = util.get_module(
        #     "tensorboard.backend.event_processing.event_file_loader",
        #     required="Please install tensorboard package",
        # )
        self.tf_compat = util.get_module(
            "tensorboard.compat", required="Please install tensorboard package"
        )
        self._tbwatcher = tbwatcher
        self._generator = self.directory_watcher.DirectoryWatcher(
            logdir, self._loader(save, namespace), self._is_our_tfevents_file
        )
        self._thread = threading.Thread(target=self._thread_body)
        self._first_event_timestamp = None
        self._shutdown = threading.Event()
        self._queue = queue
        self._file_version = None
        self._namespace = namespace
        self._logdir = logdir
        self._hostname = socket.gethostname()
        self._force = force

    def start(self) -> None:
        self._thread.start()

    def _is_our_tfevents_file(self, path: str) -> bool:
        """Checks if a path has been modified since launch and contains tfevents"""
        if not path:
            raise ValueError("Path must be a nonempty string")
        if self._force:
            return True
        path = self.tf_compat.tf.compat.as_str_any(path)
        return is_tfevents_file_created_by(
            path, self._hostname, self._tbwatcher._settings._start_time
        )

    def _loader(self, save: bool = True, namespace: str = None) -> "EventFileLoader":
        """Incredibly hacky class generator to optionally save / prefix tfevent files"""
        _loader_interface = self._tbwatcher._interface
        _loader_settings = self._tbwatcher._settings
        try:
            from tensorboard.backend.event_processing import event_file_loader
        except ImportError:
            raise Exception("Please install tensorboard package")

        class EventFileLoader(event_file_loader.EventFileLoader):
            def __init__(self, file_path: str) -> None:
                super(EventFileLoader, self).__init__(file_path)
                if save:
                    if REMOTE_FILE_TOKEN in file_path:
                        logger.warning(
                            "Not persisting remote tfevent file: %s", file_path
                        )
                    else:
                        # TODO: save plugins?
                        logdir = os.path.dirname(file_path)
                        parts = list(os.path.split(logdir))
                        if namespace and parts[-1] == namespace:
                            parts.pop()
                            logdir = os.path.join(*parts)
                        _link_and_save_file(
                            path=file_path,
                            base_path=logdir,
                            interface=_loader_interface,
                            settings=_loader_settings,
                        )

        return EventFileLoader

    def _process_events(self, shutdown_call: bool = False) -> None:
        try:
            for event in self._generator.Load():
                self.process_event(event)
        except (
            self.directory_watcher.DirectoryDeletedError,
            StopIteration,
            RuntimeError,
            OSError,
        ) as e:
            # When listing s3 the directory may not yet exist, or could be empty
            logger.debug("Encountered tensorboard directory watcher error: %s", e)
            if not self._shutdown.is_set() and not shutdown_call:
                time.sleep(ERROR_DELAY)

    def _thread_body(self) -> None:
        """Check for new events every second"""
        shutdown_time: "Optional[float]" = None
        while True:
            self._process_events()
            if self._shutdown.is_set():
                now = time.time()
                if not shutdown_time:
                    shutdown_time = now + SHUTDOWN_DELAY
                elif now > shutdown_time:
                    break
            time.sleep(1)

    def process_event(self, event: "ProtoEvent") -> None:
        # print("\nEVENT:::", self._logdir, self._namespace, event, "\n")
        if self._first_event_timestamp is None:
            self._first_event_timestamp = event.wall_time

        if event.HasField("file_version"):
            self._file_version = event.file_version

        if event.HasField("summary"):
            self._queue.put(Event(event, self._namespace))

    def shutdown(self) -> None:
        self._process_events(shutdown_call=True)
        self._shutdown.set()

    def finish(self) -> None:
        self.shutdown()
        self._thread.join()


class Event(object):
    """An event wrapper to enable priority queueing"""

    def __init__(self, event: "ProtoEvent", namespace: "Optional[str]"):
        self.event = event
        self.namespace = namespace
        self.created_at = time.time()

    def __lt__(self, other: "Event") -> bool:
        if self.event.wall_time < other.event.wall_time:
            return True
        return False


class TBEventConsumer(object):
    """Consumes tfevents from a priority queue.  There should always
    only be one of these per run_manager.  We wait for 10 seconds of queued
    events to reduce the chance of multiple tfevent files triggering
    out of order steps.
    """

    def __init__(
        self,
        tbwatcher: TBWatcher,
        queue: "PriorityQueue",
        run_proto: "RunRecord",
        settings: "SettingsStatic",
        delay: int = 10,
    ) -> None:
        self._tbwatcher = tbwatcher
        self._queue = queue
        self._thread = threading.Thread(target=self._thread_body)
        self._shutdown = threading.Event()
        self.tb_history = TBHistory()
        self._delay = delay

        # This is a bit of a hack to get file saving to work as it does in the user
        # process. Since we don't have a real run object, we have to define the
        # datatypes callback ourselves.
        def datatypes_cb(fname: str) -> None:
            files = dict(files=[(fname, "now")])
            self._tbwatcher._interface.publish_files(files)

        self._internal_run = internal_run.InternalRun(run_proto, settings, datatypes_cb)

    def start(self) -> None:
        self._start_time = time.time()
        self._thread.start()

    def finish(self) -> None:
        self._delay = 0
        self._shutdown.set()
        try:
            event = self._queue.get(True, 1)
        except queue.Empty:
            event = None
        if event:
            self._handle_event(event, history=self.tb_history)
            items = self.tb_history._get_and_reset()
            for item in items:
                self._save_row(item,)
        self._thread.join()

    def _thread_body(self) -> None:
        while True:
            try:
                event = self._queue.get(True, 1)
                # Wait self._delay seconds from consumer start before logging events
                if (
                    time.time() < self._start_time + self._delay
                    and not self._shutdown.is_set()
                ):
                    self._queue.put(event)
                    time.sleep(0.1)
                    continue
            except queue.Empty:
                event = None
                if self._shutdown.is_set():
                    break
            if event:
                self._handle_event(event, history=self.tb_history)
                items = self.tb_history._get_and_reset()
                for item in items:
                    self._save_row(item,)
        # flush uncommitted data
        self.tb_history._flush()
        items = self.tb_history._get_and_reset()
        for item in items:
            self._save_row(item)

    def _handle_event(self, event: "ProtoEvent", history: "TBHistory" = None) -> None:
        wandb.tensorboard.log(
            event.event,
            step=event.event.step,
            namespace=event.namespace,
            history=history,
        )

    def _save_row(self, row: "HistoryDict") -> None:
        chart_keys = []
        for key, item in row.items():
            if isinstance(item, CustomChart):
                panel_config = custom_chart_panel_config(item, key, key + "_table")
                config = {"panel_type": "Vega2", "panel_config": panel_config}
                chart_keys.append(key)
                self._tbwatcher._interface.publish_config(
                    val=config, key=("_wandb", "visualize", key)
                )
                row[key] = item.table

        for chart_key in chart_keys:
            table = row[chart_key]
            row.pop(chart_key)
            row[chart_key + "_table"] = table

        self._tbwatcher._interface.publish_history(
            row, run=self._internal_run, publish_step=False
        )


class TBHistory(object):
    _data: "HistoryDict"
    _added: "List[HistoryDict]"

    def __init__(self) -> None:
        self._step = 0
        self._step_size = 0
        self._data = dict()
        self._added = []

    def _flush(self) -> None:
        if not self._data:
            return
        # A single tensorboard step may have too much data
        # we just drop the largest keys in the step if it does.
        # TODO: we could flush the data across multiple steps
        if self._step_size > util.MAX_LINE_SIZE:
            metrics = [(k, sys.getsizeof(v)) for k, v in self._data.items()]
            metrics.sort(key=lambda t: t[1], reverse=True)
            bad = 0
            dropped_keys = []
            for k, v in metrics:
                # TODO: (cvp) Added a buffer of 100KiB, this feels rather brittle.
                if self._step_size - bad < util.MAX_LINE_SIZE - 100000:
                    break
                else:
                    bad += v
                    dropped_keys.append(k)
                    del self._data[k]
            wandb.termwarn(
                "Step {} exceeds max data limit, dropping {} of the largest keys:".format(
                    self._step, len(dropped_keys)
                )
            )
            print("\t" + ("\n\t".join(dropped_keys)))
        self._data["_step"] = self._step
        self._added.append(self._data)
        self._step += 1
        self._step_size = 0

    def add(self, d: "HistoryDict") -> None:
        self._flush()
        self._data = dict()
        self._data.update(self._track_history_dict(d))

    def _track_history_dict(self, d: "HistoryDict") -> "HistoryDict":
        e = {}
        for k in d.keys():
            e[k] = d[k]
            self._step_size += sys.getsizeof(e[k])
        return e

    def _row_update(self, d: "HistoryDict") -> None:
        self._data.update(self._track_history_dict(d))

    def _get_and_reset(self) -> "List[HistoryDict]":
        added = self._added[:]
        self._added = []
        return added
