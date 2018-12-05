import collections
import os
import shutil
import threading
import time
from six.moves import queue

import wandb
import wandb.util

EventFileChanged = collections.namedtuple(
    'EventFileChanged', ('path', 'save_name', 'copy'))
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


class FileStats(object):
    def __init__(self, save_name, file_path):
        """Tracks file upload progress

        save_name: the file's path in a run. It's an ID of sorts.
        file_path: the local path.
        """
        self._save_name = save_name
        self._file_path = file_path
        self.size = 0
        self.uploaded = 0

    def update_size(self):
        try:
            self.size = os.path.getsize(self._file_path)
        except (OSError, IOError):
            pass


class FilePusher(object):
    """Parallel file upload class.

    This manages uploading multiple files in parallel. It will restart a given file's
    upload job if it receives a notification that that file has been modified.
    The finish() method will block until all events have been processed and all
    uploads are complete.
    """
    """Tracks progress for files we're uploading

    Indexed by files' `save_name`'s, which are their ID's in the Run.
    """
    # We set this down to zero to avoid delays when uploading a lot of images. In one case we
    # saw logging 12 image keys per step, for 240 steps, over a 14-minute period. With 1 second
    # delay that means 48 minutes of idle.
    RATE_LIMIT_SECONDS = 0

    def __init__(self, api, max_jobs=6):
        self._files = {}  # stats

        self._api = api
        self._max_jobs = max_jobs
        self._queue = queue.Queue()
        self._last_sent = time.time() - self.RATE_LIMIT_SECONDS
        self._finished = False
        self._thread = threading.Thread(target=self._thread_body)
        self._thread.daemon = True
        self._thread.start()
        self._jobs = {}
        self._pending = []

    def update_file(self, save_name, file_path):
        if save_name not in self._files:
            self._files[save_name] = FileStats(save_name, file_path)
        self._files[save_name].update_size()

    def rename_file(self, old_save_name, new_save_name, new_path):
        """This only updates the name and path we use to track the file's size
        and upload progress. Doesn't rename it on the back end or make us
        upload from anywhere else.
        """
        if old_save_name in self._files:
            del self._files[old_save_name]
        self.update_file(new_save_name, new_path)

    def update_all_files(self):
        for file_stats in self._files.values():
            file_stats.update_size()

    def update_progress(self, save_name, uploaded):
        # TODO(adrian): this check sucks but we rely on it for weird W&B files
        # like wandb-summary.json and config.yaml. Not sure why.
        if save_name in self._files:
            self._files[save_name].uploaded = uploaded

    def print_status(self):
        step = 0
        spinner_states = ['-', '\\', '|', '/']
        stop = False
        while True:
            if not self.is_alive():
                stop = True
            summary = self.summary()
            line = (' %(completed_files)s of %(total_files)s files,'
                    ' %(uploaded_bytes).03f of %(total_bytes).03f bytes uploaded\r' % summary)
            line = spinner_states[step % 4] + line
            step += 1
            wandb.termlog(line, newline=False)
            if stop:
                break
            time.sleep(0.25)
        # clear progress line.
        wandb.termlog(' ' * 79)

    def files(self):
        return self._files.keys()

    def stats(self):
        return self._files

    def summary(self):
        return {
            'completed_files': sum(f.size == f.uploaded for f in self._files.values()),
            'total_files': len(self._files),
            'uploaded_bytes': sum(f.uploaded for f in self._files.values()),
            'total_bytes': sum(f.size for f in self._files.values())
        }

    def _push_function(self, save_name, path):
        try:
            with open(path, 'rb') as f:
                self._api.push({save_name: f},
                               progress=lambda _, total: self.update_progress(save_name, total))
        except Exception as e:
            # Give up uploading the file by pretending it's finished
            # TODO(adrian): Really we should count these separately from successful ones
            self._files[save_name].uploaded = self._files[save_name].size
            wandb.util.sentry_exc(e)
            wandb.termerror('Error uploading "{}": {}, {}'.format(
                save_name, type(e).__name__, e))

    def _thread_body(self):
        while True:
            event = self._queue.get()
            if isinstance(event, EventFinish):
                self._finished = True
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
                self._start_job(event.job.save_name,
                                event.job.path, event.job.copy)
            elif self._pending:
                event = self._pending.pop()
                self._start_job(event.save_name, event.path, event.copy)
        elif isinstance(event, EventFileChanged):
            if len(self._jobs) == self._max_jobs:
                self._pending.append(event)
            else:
                self._start_job(event.save_name, event.path, event.copy)

    def _start_job(self, save_name, path, copy):
        if save_name in self._jobs:
            self._jobs[save_name].restart()
            return

        job = UploadJob(self._queue, self._push_function,
                        save_name, path, copy)
        if self._finished or self._last_sent < time.time() - self.RATE_LIMIT_SECONDS:
            job.start()
            self._jobs[save_name] = job
            self._last_sent = time.time()
        else:
            time.sleep(self.RATE_LIMIT_SECONDS)
            self._start_job(save_name, path, copy)

    def file_changed(self, save_name, path, copy=False):
        # Tests in linux were failing because wandb-events.jsonl didn't exist
        if os.path.exists(path) and os.path.getsize(path) != 0:
            self._queue.put(EventFileChanged(path, save_name, copy))

    def finish(self):
        self._queue.put(EventFinish())

    def shutdown(self):
        self.finish()
        self._thread.join()

    def is_alive(self):
        return self._thread.is_alive()
