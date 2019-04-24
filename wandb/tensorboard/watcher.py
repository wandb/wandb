from tensorboard.backend.event_processing import directory_watcher
from tensorboard.backend.event_processing import event_file_loader
from tensorboard.backend.event_processing import io_wrapper
from wandb.tensorboard import log
from wandb import util
import six
from six.moves import queue
import wandb
import time
import threading
import collections


class Event(object):
    def __init__(self, event, namespace):
        self.event = event
        self.namespace = namespace
        self.created_at = event.wall_time

    def __lt__(self, other):
        return self.event.step < other.event.step


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
        self._delay = 10

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


class Watcher(object):
    def __init__(self, logdir, queue, namespace=None):
        self.namespace = namespace
        self.queue = queue
        self.logdir = logdir
        self._generator = directory_watcher.DirectoryWatcher(
            logdir,
            event_file_loader.EventFileLoader,
            io_wrapper.IsTensorFlowEventsFile)
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
            hparam = False
            for value in event.summary.value:
                if value.tag == "_hparams_/session_start_info":
                    hparam = True
                    if util.get_module("tensorboard.plugins.hparams"):
                        from tensorboard.plugins.hparams import plugin_data_pb2
                        plugin_data = plugin_data_pb2.HParamsPluginData()
                        plugin_data.ParseFromString(
                            value.metadata.plugin_data.content)
                        for key, param in six.iteritems(plugin_data.session_start_info.hparams):
                            if not wandb.run.config.get(key):
                                wandb.run.config[key] = param.number_value or param.string_value or param.bool_value
                    else:
                        wandb.termerror(
                            "Received hparams tf.summary, but could not import the hparams plugin from tensorboard")
            if not hparam:
                self.queue.put(Event(event, self.namespace))
