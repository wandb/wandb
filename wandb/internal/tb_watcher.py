"""
tensor b watcher.
"""

import os
import threading
import time

import six
from six.moves import queue
import wandb
from wandb import util
from wandb.internal import run as internal_run


# Give some time for tensorboard data to be flushed
SHUTDOWN_DELAY = 5


def _link_and_save_file(path, base_path, interface, settings):
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


class TBWatcher(object):
    def __init__(self, settings, run_proto, interface):
        self._logdirs = {}
        self._consumer = None
        self._settings = settings
        self._interface = interface
        self._internal_run = internal_run.InternalRun(run_proto, settings)
        # TODO(jhr): do we need locking in this queue?
        self._watcher_queue = queue.PriorityQueue()
        wandb.tensorboard.reset_state()

    def _calculate_namespace(self, logdir):
        dirs = list(self._logdirs) + [logdir]
        rootdir = os.path.dirname(os.path.commonprefix(dirs))
        if os.path.isfile(logdir):
            filename = os.path.basename(logdir)
        else:
            filename = ""
        # Tensorboard loads all tfevents files in a directory and prepends
        # their values with the path.  Passing namespace to log allows us
        # to nest the values in wandb
        namespace = logdir.replace(filename, "").replace(rootdir, "").strip(os.sep)
        # TODO: revisit this heuristic, it exists because we don't know the
        # root log directory until more than one tfevents file is written to
        if len(dirs) == 1 and namespace not in ["train", "validation"]:
            namespace = None
        return namespace

    def add(self, logdir, save):
        if logdir in self._logdirs:
            return
        namespace = self._calculate_namespace(logdir)
        # TODO(jhr): implement the deferred tbdirwatcher to find namespace

        if not self._consumer:
            self._consumer = TBEventConsumer(
                self, self._watcher_queue, self._internal_run
            )
            self._consumer.start()

        tbdir_watcher = TBDirWatcher(self, logdir, save, namespace, self._watcher_queue)
        self._logdirs[logdir] = tbdir_watcher
        tbdir_watcher.start()

    def finish(self):
        for tbdirwatcher in six.itervalues(self._logdirs):
            tbdirwatcher.shutdown()
        for tbdirwatcher in six.itervalues(self._logdirs):
            tbdirwatcher.finish()
        if self._consumer:
            self._consumer.finish()


class TBDirWatcher(object):
    def __init__(self, tbwatcher, logdir, save, namespace, queue):
        self.directory_watcher = util.get_module(
            "tensorboard.backend.event_processing.directory_watcher",
            required="Please install tensorboard package",
        )
        self.event_file_loader = util.get_module(
            "tensorboard.backend.event_processing.event_file_loader",
            required="Please install tensorboard package",
        )
        self.tf_compat = util.get_module(
            "tensorboard.compat", required="Please install tensorboard package"
        )
        self._tbwatcher = tbwatcher
        self._generator = self.directory_watcher.DirectoryWatcher(
            logdir, self._loader(save, namespace), self._is_new_tensorflow_events_file
        )
        self._thread = threading.Thread(target=self._thread_body)
        self._first_event_timestamp = None
        self._shutdown = None
        self._queue = queue
        self._file_version = None
        self._namespace = namespace
        self._logdir = logdir

    def start(self):
        self._thread.start()

    def _is_new_tensorflow_events_file(self, path):
        """Checks if a path has been modified since launch and contains tfevents"""
        if not path:
            raise ValueError("Path must be a nonempty string")
        path = self.tf_compat.tf.compat.as_str_any(path)
        base = os.path.basename(path)
        start_time = self._tbwatcher._settings._start_time
        return (
            "tfevents" in base
            and os.stat(path).st_mtime >= start_time  # noqa: W503
            and not base.endswith(".profile-empty")  # noqa: W503
        )

    def _loader(self, save=True, namespace=None):
        """Incredibly hacky class generator to optionally save / prefix tfevent files"""
        _loader_interface = self._tbwatcher._interface
        _loader_settings = self._tbwatcher._settings

        class EventFileLoader(self.event_file_loader.EventFileLoader):
            def __init__(self, file_path):
                super(EventFileLoader, self).__init__(file_path)
                if save:
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

    def _thread_body(self):
        """Check for new events every second"""
        shutdown_time = None
        while True:
            try:
                for event in self._generator.Load():
                    self.process_event(event)
            except self.directory_watcher.DirectoryDeletedError:
                break
            if self._shutdown:
                now = time.time()
                if not shutdown_time:
                    shutdown_time = now + SHUTDOWN_DELAY
                elif now > shutdown_time:
                    break
            time.sleep(1)

    def process_event(self, event):
        # print("\nEVENT:::", self._logdir, self._namespace, event, "\n")
        if self._first_event_timestamp is None:
            self._first_event_timestamp = event.wall_time

        if event.HasField("file_version"):
            self._file_version = event.file_version

        if event.HasField("summary"):
            self._queue.put(Event(event, self._namespace))

    def shutdown(self):
        self._shutdown = True

    def finish(self):
        self.shutdown()
        self._thread.join()


class Event(object):
    """An event wrapper to enable priority queueing"""

    def __init__(self, event, namespace):
        self.event = event
        self.namespace = namespace
        self.created_at = time.time()

    def __lt__(self, other):
        return self.event.wall_time < other.event.wall_time


class TBEventConsumer(object):
    """Consumes tfevents from a priority queue.  There should always
    only be one of these per run_manager.  We wait for 10 seconds of queued
    events to reduce the chance of multiple tfevent files triggering
    out of order steps.
    """

    def __init__(self, tbwatcher, queue, internal_run, delay=10):
        self._tbwatcher = tbwatcher
        self._queue = queue
        self._internal_run = internal_run
        self._thread = threading.Thread(target=self._thread_body)
        self._shutdown = None
        self._delay = delay

    def start(self):
        self._thread.start()

    def finish(self):
        self._delay = 0
        self._shutdown = True
        self._thread.join()

    def _thread_body(self):
        tb_history = TBHistory()
        while True:
            try:
                event = self._queue.get(True, 1)
                # If the event was added later than delay, put it back in the queue
                if event.created_at > time.time() - self._delay:
                    self._queue.put(event)
                    time.sleep(0.1)
                    continue
            except queue.Empty:
                event = None
                if self._shutdown:
                    break
            if event:
                self._handle_event(event, history=tb_history)
                items = tb_history._get_and_reset()
                for item in items:
                    self._save_row(item,)
        # flush uncommitted data
        tb_history._flush()
        items = tb_history._get_and_reset()
        for item in items:
            self._save_row(item)

    def _handle_event(self, event, history=None):
        wandb.tensorboard.log(
            event.event,
            step=event.event.step,
            namespace=event.namespace,
            history=history,
        )

    def _save_row(self, row):
        self._tbwatcher._interface.publish_history(row, run=self._internal_run)


class TBHistory(object):
    def __init__(self):
        self._step = 0
        self._data = dict()
        self._added = []

    def _flush(self):
        if not self._data:
            return
        self._data["_step"] = self._step
        self._added.append(self._data)
        self._step += 1

    def add(self, d):
        self._flush()
        self._data = dict()
        self._data.update(d)

    def _row_update(self, d):
        self._data.update(d)

    def _get_and_reset(self):
        added = self._added[:]
        self._added = []
        return added
