import collections
import os
import shutil
import threading
import time
from six.moves import queue

import wandb


EventFileChanged = collections.namedtuple('EventFileChanged', ('path', 'save_name', 'copy'))
EventJobDone = collections.namedtuple('EventJobDone', ('job'))
EventFinish = collections.namedtuple('EventFinish', ())


class UploadJob(threading.Thread):
    def __init__(self, done_queue, push_function, save_name, path, copy=False):
        self._done_queue = done_queue
        self._push_function = push_function
        self.save_name = save_name
        self.path = path
        self.copy = copy
        self.needs_restart = False
        super(UploadJob, self).__init__()

    def run(self):
        try:
            #wandb.termlog('Uploading file: %s' % self.save_name)
            save_path = self.path
            if self.copy:
                save_path = self.path + '.tmp'
                shutil.copy2(self.path, save_path)
            self._push_function(self.save_name, save_path)
            if self.copy:
                os.remove(save_path)
            #wandb.termlog('Done uploading file: %s' % self.save_name)
        finally:
            self._done_queue.put(EventJobDone(self))

    def restart(self):
        # In the future, this could cancel the current upload and restart it. The logic
        # should go in FilePusher to avoid raciness (it would call job.cancel(),
        # and then restart it).
        self.needs_restart = True


class FilePusher(object):
    """Parallel file upload class.

    This manages uploading multiple files in parallel. It will restart a given file's
    upload job if it receives a notification that that file has been modified.
    The finish() method will block until all events have been processed and all
    uploads are complete.
    """
    def __init__(self, push_function, max_jobs=4):
        self._push_function = push_function
        self._max_jobs = max_jobs
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._thread_body)
        self._thread.daemon = True
        self._thread.start()
        self._jobs = {}
        self._pending = []

    def _thread_body(self):
        while True:
            event = self._queue.get()
            if isinstance(event, EventFinish):
                break
            self._handle_event(event)

        while True:
            try:
                event = self._queue.get(True, 1)
            except queue.Empty:
                event = None
            if event:
                self._handle_event(event)
            elif not self._jobs:
                # Queue was empty and no jobs left.
                break

    def _handle_event(self, event):
        if isinstance(event, EventJobDone):
            job = event.job
            job.join()
            self._jobs.pop(job.save_name)
            if job.needs_restart:
                #wandb.termlog('File changed while uploading, restarting: %s' % event.job.save_name)
                self._start_job(event.job.save_name, event.job.path, event.job.copy)
            elif self._pending:
                event = self._pending.pop()
                self._start_job(event.save_name, event.path, event.copy)
        elif isinstance(event, EventFileChanged):
            if event.save_name in self._jobs:
                self._jobs[event.save_name].restart()
            elif len(self._jobs) == self._max_jobs:
                self._pending.append(event)
            else:
                self._start_job(event.save_name, event.path, event.copy)

    def _start_job(self, save_name, path, copy):
        job = UploadJob(self._queue, self._push_function, save_name, path, copy)
        job.start()
        self._jobs[save_name] = job

    def file_changed(self, save_name, path, copy=False):
        self._queue.put(EventFileChanged(path, save_name, copy))

    def finish(self):
        self._queue.put(EventFinish())

    def is_alive(self):
        return self._thread.is_alive()