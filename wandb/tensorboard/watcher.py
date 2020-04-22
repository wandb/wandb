from __future__ import absolute_import
import sys
import os
from wandb import util
# Ensure we don't have the wandb directory in the path to avoid importing our tensorboard
# module.  This should only happen when wandb is installed with pip -e or pip install ...#egg=wandb
for path in sys.path:
    if path.endswith(os.path.join("client", "wandb")):
        sys.path.remove(path)
    if path.endswith(os.path.join("site-packages", "wandb")):
        sys.path.remove(path)
if sys.modules.get("tensorboard"):
    # Remove tensorboard if it's us
    if hasattr(util.get_module("tensorboard"), "TENSORBOARD_C_MODULE"):
        del sys.modules["tensorboard"]
from tensorboard.backend.event_processing import directory_watcher
from tensorboard.backend.event_processing import event_file_loader
from tensorboard.compat import tf
from wandb.tensorboard import log
import six
import os
from six.moves import queue
import wandb
import time
import threading
import collections


class Event(object):
    """An event wrapper to enable priority queueing"""

    def __init__(self, event, namespace):
        self.event = event
        self.namespace = namespace
        self.created_at = time.time()

    def __lt__(self, other):
        return self.event.wall_time < other.event.wall_time


class Consumer(object):
    """Consumes tfevents from a priority queue.  There should always
    only be one of these per run_manager.  We wait for 10 seconds of queued
    events to reduce the chance of multiple tfevent files triggering
    out of order steps.
    """

    def __init__(self, queue, delay=10):
        self._queue = queue
        self._thread = threading.Thread(target=self._thread_body)
        self._thread.daemon = True
        self._shutdown = False
        self._delay = delay

    def start(self):
        self._thread.start()

    def shutdown(self):
        self._delay = 0
        self._shutdown = True
        try:
            self._thread.join()
        # Incase we never start it
        except RuntimeError:
            pass

    def _thread_body(self):
        while True:
            try:
                event = self._queue.get(True, 1)
                # If the event was added later than delay, put it back in the queue
                if event.created_at > time.time() - self._delay:
                    self._queue.put(event)
                    time.sleep(0.1)
            except queue.Empty:
                event = None
                if self._shutdown:
                    break
            if event:
                self._handle_event(event)

    def _handle_event(self, event):
        log(event.event, step=event.event.step, namespace=event.namespace)


def loader(save=True, namespace=None):
    """Incredibly hacky class generator to optionally save / prefix tfevent files"""
    class EventFileLoader(event_file_loader.EventFileLoader):
        def __init__(self, file_path):
            super(EventFileLoader, self).__init__(file_path)
            if save:
                # TODO: save plugins?
                logdir = os.path.dirname(file_path)
                parts = list(os.path.split(logdir))
                if namespace and parts[-1] == namespace:
                    parts.pop()
                    logdir = os.path.join(*parts)
                wandb.save(file_path, base_path=logdir)
    return EventFileLoader


def IsNewTensorFlowEventsFile(path):
    """Checks if a path has been modified since launch and contains tfevents"""
    if not path:
        raise ValueError('Path must be a nonempty string')
    path = tf.compat.as_str_any(path)
    return 'tfevents' in os.path.basename(path) and os.stat(path).st_mtime >= wandb.START_TIME


class Watcher(object):
    def __init__(self, logdir, queue, namespace=None, save=True):
        """Uses tensorboard to watch a directory for tfevents files 
        and put them on a queue"""
        self.namespace = namespace
        self.queue = queue
        self.logdir = logdir
        # TODO: prepend the namespace here?
        self._generator = directory_watcher.DirectoryWatcher(
            logdir,
            loader(save, namespace),
            IsNewTensorFlowEventsFile)
        self._first_event_timestamp = None
        self._shutdown = False
        self._thread = threading.Thread(target=self._thread_body)
        self._thread.daemon = True

    def start(self):
        self._thread.start()

    def shutdown(self):
        self._shutdown = True
        try:
            self._thread.join()
        # Incase we never start it
        except RuntimeError:
            pass

    def _thread_body(self):
        """Check for new events every second"""
        while True:
            try:
                for event in self._generator.Load():
                    self.process_event(event)
            except directory_watcher.DirectoryDeletedError:
                break
            if self._shutdown:
                break
            else:
                time.sleep(1)

    def process_event(self, event):
        if self._first_event_timestamp is None:
            self._first_event_timestamp = event.wall_time

        if event.HasField('file_version'):
            self.file_version = event.file_version

        if event.HasField('summary'):
            self.queue.put(Event(event, self.namespace))
