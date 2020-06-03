import collections
import os
import shutil
import threading
import time
from six.moves import queue
import warnings
import tarfile

import wandb
import wandb.util
from wandb.compat import tempfile

def resolve_path(path):
    try:
        from pathlib import Path
        return str(Path(path).resolve())
    except:
        # Pathlib isn't present for python versions earlier than 3.3
        return os.path.realpath(path)

# Get rid of cleanup warnings in Python 2.7.
warnings.filterwarnings('ignore', 'Implicitly cleaning up', RuntimeWarning, 'wandb.compat.tempfile')


# Temporary directory for copies we make of some file types to
# reduce the probability that the file gets changed while we're
# uploading it.
TMP_DIR = tempfile.TemporaryDirectory('wandb')


EventFileBatch = collections.namedtuple(
    'EventFileBatch', ('batch_id', 'file_changed_events',))
EventFileChanged = collections.namedtuple(
    'EventFileChanged', ('path', 'save_name', 'copy'))
EventJobDone = collections.namedtuple('EventJobDone', ('job'))
EventFinish = collections.namedtuple('EventFinish', ())


class UploadJob(threading.Thread):
    def __init__(self, done_queue, progress, api, save_name, path, copy=True):
        """A file upload thread.

        Arguments:
            done_queue: queue.Queue in which to put an EventJobDone event when
                the upload finishes.
            push_function: function(save_name, actual_path) which actually uploads
                the file.
            save_name: string logical location of the file relative to the run
                directory.
            path: actual string path of the file to upload on the filesystem.
            copy: (bool) Whether to copy the file before uploading it. Defaults
                to True because if you try to upload a file while it's being
                rewritten, it's possible that we'll upload something truncated
                or corrupt. Our file-uploading rules are generally designed
                so that that won't happen during normal operation.
        """
        self._done_queue = done_queue
        self._progress = progress
        self._api = api
        self.save_name = save_name
        self.save_path = self.path = path
        self.copy = copy
        self.needs_restart = False
        self.label = save_name
        super(UploadJob, self).__init__()

    def prepare_file(self):
        if self.copy:
            self.save_path = os.path.join(TMP_DIR.name, self.save_name)
            wandb.util.mkdir_exists_ok(os.path.dirname(self.save_path))
            shutil.copy2(self.path, self.save_path)

    def cleanup_file(self):
        if self.copy and os.path.isfile(self.save_path):
            os.remove(self.save_path)

    def run(self):
        try:
            # wandb.termlog('Uploading file: %s' % self.save_name)
            self.prepare_file()
            self.push()
            # wandb.termlog('Done uploading file: %s' % self.save_name)
        finally:
            self.cleanup_file()
            self._done_queue.put(EventJobDone(self))

    def push(self):
        try:
            size = os.path.getsize(self.save_path)
        except OSError:
            size = 0

        self._progress[self.label] = {
            'total': size,
            'uploaded': 0,
            'failed': False
        }
        try:
            with open(self.save_path, 'rb') as f:
                self._api.push(
                    {self.save_name: f},
                    progress=lambda _, t: self.progress(t))
        except Exception as e:
            self._progress[self.label]['uploaded'] = 0
            self._progress[self.label]['failed'] = True
            wandb.util.sentry_exc(e)
            wandb.termerror('Error uploading "{}": {}, {}'.format(
                self.save_name, type(e).__name__, e))

    def progress(self, total_bytes):
        if self.label not in self._progress:
            return
        self._progress[self.label]['uploaded'] = total_bytes

    def restart(self):
        # In the future, this could cancel the current upload and restart it. The logic
        # should go in FilePusher to avoid raciness (it would call job.cancel(),
        # and then restart it).
        self.needs_restart = True


class BatchUploadJob(UploadJob):
    def __init__(self, done_queue, files, api, batch_id, file_changed_events):
        # Copy all files to a temp dir in the correct structure
        tgz_path = os.path.join(TMP_DIR.name, 'batch-%s.tgz' % batch_id)
        # wandb.termlog('Preparing batch: %s' % tgz_path)

        with tarfile.open(tgz_path, 'w:gz') as tar:
            for event in file_changed_events:
                try:
                    tar.add(resolve_path(event.path), arcname=event.save_name)
                except OSError:
                    # Retry once, then show an error and continue
                    time.sleep(0.1)
                    try:
                        tar.add(resolve_path(event.path),
                            arcname=event.save_name)
                    except OSError:
                        wandb.termwarn("Failed to add %s to batch archive." %
                            event.save_name)

        save_name = '___batch_archive_{}.tgz'.format(batch_id)

        super(BatchUploadJob, self).__init__(done_queue, files, api, save_name,
            tgz_path)

        self.label = 'batch_{}'.format(batch_id)
        self.tgz_path = tgz_path

    def cleanup_file(self):
        super(BatchUploadJob, self).cleanup_file()
        # wandb.termlog('Cleaning batch: %s' % self.tgz_path)
        os.unlink(self.tgz_path)


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
        self.failed = False

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

    # After 5 seconds of gathering batched uploads, kick off a batch without
    # waiting any longer.
    BATCH_THRESHOLD_SECS = 3

    # Maximum number of files in any given batch. If there are too many files
    # it can take too long to unpack -- 500 very small files takes GCP about a
    # minute.
    BATCH_MAX_FILES = 100

    # If there are fewer than this many files gathered over a batch threshold, 
    # then just upload them individually.
    BATCH_MIN_FILES = 3

    # If needed you can space out uploads a bit.
    RATE_LIMIT_SECS = 0.1

    def __init__(self, api, max_jobs=6):
        self._file_stats = {}  # stats for all files
        self._progress = {}   # amount uploaded
        self._batch_num = 1  # incrementing counter for archive filenamess

        self._api = api
        self._max_jobs = max_jobs
        self._batch_queue = queue.Queue()
        self._event_queue = queue.Queue()
        self._last_job_started_at = 0
        self._finished = False

        # Thread for processing events and starting upload jobs
        self._process_thread = threading.Thread(target=self._process_body)
        self._process_thread.daemon = True
        self._process_thread.start()

        # Thread for gathering batches and creating a single upload job.
        self._batch_thread = threading.Thread(target=self._batch_body)
        self._batch_thread.daemon = True
        self._batch_thread.start()

        # Indexed by files' `save_name`'s, which are their ID's in the Run.
        self._running_jobs = {}
        self._pending_events = []

    def update_file(self, save_name, file_path):
        if save_name not in self._file_stats:
            self._file_stats[save_name] = FileStats(save_name, file_path)
        self._file_stats[save_name].update_size()

    def rename_file(self, old_save_name, new_save_name, new_path):
        """This only updates the name and path we use to track the file's size
        and upload progress. Doesn't rename it on the back end or make us
        upload from anywhere else.
        """
        if old_save_name in self._file_stats:
            del self._file_stats[old_save_name]
        self.update_file(new_save_name, new_path)

    def update_all_files(self):
        for file_stats in self._file_stats.values():
            file_stats.update_size()

    def print_status(self):
        step = 0
        spinner_states = ['-', '\\', '|', '/']
        stop = False
        while True:
            if not self.is_alive():
                stop = True
            summary = self.summary()
            line = ' %.2fMB of %.2fMB uploaded\r' % (
                summary['uploaded_bytes'] / 1048576.0,
                summary['total_bytes'] / 1048576.0)
            line = spinner_states[step % 4] + line
            if summary['failed_batches']:
                line += ' (%(failed_batches)d failed uploads)'
            step += 1
            wandb.termlog(line, newline=False)
            if stop:
                break
            time.sleep(0.25)
        # clear progress line.
        wandb.termlog(' ' * 79)

    def files(self):
        return self._file_stats.keys()

    def stats(self):
        return self._file_stats

    def summary(self):
        progress_values = list(self._progress.values())
        return {
            'failed_batches': len([f for f in progress_values if f['failed']]),
            'uploaded_bytes': sum(f['uploaded'] for f in progress_values),
            'total_bytes': sum(f['total'] for f in progress_values)
        }

    def _process_body(self):
        # Wait for event in the queue, and process one by one until a
        # finish event is received
        while True:
            event = self._event_queue.get()
            if isinstance(event, EventFinish):
                self._finished = True
                break
            self._process_event(event)

        # After a finish event is received, iterate through the event queue
        # one by one and process all remaining events.
        while True:
            try:
                event = self._event_queue.get(True, 1)
            except queue.Empty:
                event = None
            if event:
                self._process_event(event)
            elif not self._running_jobs:
                # Queue was empty and no jobs left.
                break

    def _batch_body(self):
        # Repeat core loop infinitely until a Finish event is received. Once
        # we've received a finish event, we can terminate the batch thread
        # immediately since it's guaranteed no further file change events
        # will come in.
        finished = False
        while True:
            batch = []
            batch_started_at = time.time()
            batch_end_at = batch_started_at + self.BATCH_THRESHOLD_SECS
            while time.time() < batch_end_at and len(batch) < self.BATCH_MAX_FILES:
                # Get the latest event
                try:
                    wait_secs = batch_end_at - time.time()
                    event = self._batch_queue.get(timeout=wait_secs)
                except queue.Empty:
                    # If nothing is available in the batch by the timeout
                    # wrap up and send the current batch immediately.
                    break
                # If it's a finish, stop waiting and send the current batch
                # immediately.
                if isinstance(event, EventFinish):
                    finished = True
                    break
                # Otherwise, it's file changed, so add it to the pending batch.
                batch.append(event)

            if batch:
                if len(batch) <= self.BATCH_MIN_FILES:
                    # If less than the minimum files are found, just upload
                    # them individually.
                    for event in set(batch):
                        self._event_queue.put(event)
                else:
                    # Otherwise, send all the files as a batch.
                    new_batch_id = str(self._batch_num)
                    self._event_queue.put(EventFileBatch(new_batch_id, list(set(batch))))
                    self._batch_num += 1
            
            # And stop the infinite loop if we've finished
            if finished:
                break

    def _process_event(self, event):
        if isinstance(event, EventJobDone):
            job = event.job
            job.join()
            self._running_jobs.pop(job.label)
            if job.needs_restart:
                #wandb.termlog('File changed while uploading, restarting: %s' % event.job.save_name)
                self._start_or_restart_event_job(event)
            elif self._pending_events:
                event = self._pending_events.pop()
                self._start_or_restart_event_job(event)
            return

        # If it gets here, must be a FileChanged or FileBatch event
        if len(self._running_jobs) == self._max_jobs:
            self._pending_events.append(event)
            return
            
        # Start now if we have capacity
        self._start_or_restart_event_job(event)

    def _label_for_event(self, event):
        if isinstance(event, EventFileChanged):
            return event.save_name
        if isinstance(event, EventFileBatch):
            return 'batch_{}'.format(event.batch_id)
        return None

    def _start_or_restart_event_job(self, event):
        label = self._label_for_event(event)
        if not label:
            return

        # Restart if in running jobs
        if label in self._running_jobs:
            self._running_jobs[label].restart()
            return

        # Rate limit if it's too fast to prevent overloading the server
        elapsed_since_last = time.time() - self._last_job_started_at
        if elapsed_since_last < self.RATE_LIMIT_SECS:
            time.sleep(self.RATE_LIMIT_SECS - elapsed_since_last)
            self._start_or_restart_event_job(event)
            return

        # Or start
        self._last_job_started_at = time.time()
        self._running_jobs[label] = self._start_event_job(label, event)

    def _start_event_job(self, label, event):
        if isinstance(event, EventFileChanged):
            return self._start_single_job(event.save_name, event.path,
                event.copy)

        if isinstance(event, EventFileBatch):
            return self._start_batch_job(event.batch_id,
                event.file_changed_events)

    def _start_single_job(self, save_name, path, copy):
        # wandb.termlog("Starting individual upload: %s" % save_name)
        job = UploadJob(self._event_queue, self._progress, self._api, save_name, path, copy)
        job.start()
        return job

    def _start_batch_job(self, batch_id, file_changed_events):
        # wandb.termlog("Starting batch %s (%d files)" % (batch_id,
        #     len(file_changed_events)))
        job = BatchUploadJob(self._event_queue, self._progress, self._api,
            batch_id, file_changed_events)
        job.start()
        return job

    def should_batch(self, file_change_event):
        """
        Whether a file gets batched depends on file size. Anything above
        1MB should be handled individually.
        """
        return os.path.getsize(file_change_event.path) < 1000000

    def file_changed(self, save_name, path, copy=True):
        """Tell the file pusher that a file's changed and should be uploaded.

        Arguments:
            save_name: string logical location of the file relative to the run
                directory.
            path: actual string path of the file to upload on the filesystem.
            copy: (bool) Whether to copy the file before uploading it. Defaults
                to True because if you try to upload a file while it's being
                rewritten, it's possible that we'll upload something truncated
                or corrupt. Our file-uploading rules are generally designed
                so that that won't happen during normal operation.
        """
        # Tests in linux were failing because wandb-events.jsonl didn't exist
        if not os.path.exists(path):
            return
        if os.path.getsize(path) == 0:
            return

        event = EventFileChanged(path, save_name, copy)

        if self.should_batch(event):
            self._batch_queue.put(event)
        else:
            self._event_queue.put(event)

    def finish(self):
        self._event_queue.put(EventFinish())
        self._batch_queue.put(EventFinish())

    def shutdown(self):
        self.finish()
        self._batch_thread.join()
        self._process_thread.join()

    def is_alive(self):
        return self._process_thread.is_alive() or self._batch_thread.is_alive()
