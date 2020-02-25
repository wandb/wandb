# Potential improvements:
#   - when add to pending_jobs, we should look and see if we already have a job
#     for this file, if so, don't bother adding it. We don't need more than
#     one pending
import collections
import os
import shutil
import threading
import time
from six.moves import queue
import warnings
import tarfile
import multiprocessing

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


# This is handled by the batching thread
UploadRequest = collections.namedtuple(
    'EventUploadRequest', ('path', 'save_name', 'artifact_id'))
CommitArtifactRequest = collections.namedtuple('EventCommitArtifactRequest',
                                               ('artifact_id', ))

# These are handled by the event thread
EventStartUploadJob = collections.namedtuple(
    'EventStartUploadJob', ('path', 'save_name'))
EventJobDone = collections.namedtuple('EventJobDone', ('job'))
EventFinish = collections.namedtuple('EventFinish', ())


class UploadJob(threading.Thread):
    def __init__(self, done_queue, progress, api, save_name, path):
        """A file upload thread.

        Arguments:
            done_queue: queue.Queue in which to put an EventJobDone event when
                the upload finishes.
            push_function: function(save_name, actual_path) which actually uploads
                the file.
            save_name: string logical location of the file relative to the run
                directory.
            path: actual string path of the file to upload on the filesystem.
        """
        self._done_queue = done_queue
        self._progress = progress
        self._api = api
        self.save_name = save_name
        self.save_path = self.path = path
        super(UploadJob, self).__init__()

    def run(self):
        try:
            self.push()
        finally:
            self._done_queue.put(EventJobDone(self))

    def push(self):
        try:
            size = os.path.getsize(self.save_path)
        except OSError:
            size = 0

        self._progress[self.save_name] = {
            'deduped': False,
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
            self._progress[self.save_name]['uploaded'] = 0
            self._progress[self.save_name]['failed'] = True
            wandb.util.sentry_exc(e)
            wandb.termerror('Error uploading "{}": {}, {}'.format(
                self.save_name, type(e).__name__, e))

    def progress(self, total_bytes):
        if self.save_name not in self._progress:
            return
        self._progress[self.save_name]['uploaded'] = total_bytes


class FilePusher(object):
    """Parallel file upload class.

    This manages uploading multiple files in parallel. It will restart a given file's
    upload job if it receives a notification that that file has been modified.
    The finish() method will block until all events have been processed and all
    uploads are complete.
    """

    # After 3 seconds of gathering batched uploads, kick off a batch without
    # waiting any longer.
    BATCH_THRESHOLD_SECS = 3

    BATCH_MAX_FILES = 1000

    def __init__(self, api, max_jobs=64):
        self._file_stats = {}  # stats for all files
        self._progress = {}   # amount uploaded

        self._api = api
        self._max_jobs = max_jobs
        self._checksum_queue = queue.Queue()
        self._event_queue = queue.Queue()
        self._last_job_started_at = 0
        self._finished = False

        # TODO: Bigger is probably better for some workloads
        self._pool = multiprocessing.Pool(4)

        # Thread for processing events and starting checksum jobs
        self._checksum_thread = threading.Thread(target=self._checksum_body)
        self._checksum_thread.daemon = True
        self._checksum_thread.start()

        # Thread for processing events and starting upload jobs
        self._process_thread = threading.Thread(target=self._process_body)
        self._process_thread.daemon = True
        self._process_thread.start()

        # Indexed by files' `save_name`'s, which are their ID's in the Run.
        self._running_jobs = {}
        self._pending_jobs = []

    def print_status(self):
        step = 0
        spinner_states = ['-', '\\', '|', '/']
        stop = False
        while True:
            if not self.is_alive():
                stop = True
            summary = self.summary()
            line = ' %.2fMB of %.2fMB uploaded (%.2fMB deduped). %s files\r' % (
                summary['uploaded_bytes'] / 1048576.0,
                summary['total_bytes'] / 1048576.0,
                summary['deduped_bytes'] / 1048576.0,
                summary['nfiles'])
            line = spinner_states[step % 4] + line
            step += 1
            wandb.termlog(line, newline=False)
            if stop:
                break
            time.sleep(0.25)
        if summary['deduped_bytes'] != 0:
            wandb.termlog('✨ W&B magic sync reduced upload amount by %.1f%%             ' %
                          (summary['deduped_bytes'] / float(summary['total_bytes']) * 100))
        # clear progress line.
        wandb.termlog(' ' * 79)

    def files(self):
        return self._progress.keys()

    def summary(self):
        progress_values = list(self._progress.values())
        return {
            'nfiles': len(progress_values),
            'uploaded_bytes': sum(f['uploaded'] for f in progress_values),
            'total_bytes': sum(f['total'] for f in progress_values),
            'deduped_bytes': sum(f['total'] for f in progress_values if f['deduped'])
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

    def _checksum_body(self):
        finished = False
        while True:
            artifact_commits = []
            batch = []
            batch_started_at = time.time()
            batch_end_at = batch_started_at + self.BATCH_THRESHOLD_SECS
            while time.time() < batch_end_at and len(batch) < self.BATCH_MAX_FILES:
                # Get the latest event
                try:
                    wait_secs = batch_end_at - time.time()
                    event = self._checksum_queue.get(timeout=wait_secs)
                except queue.Empty:
                    # If nothing is available in the batch by the timeout
                    # wrap up and send the current batch immediately.
                    break
                # If it's a finish, stop waiting and send the current batch
                # immediately.
                if isinstance(event, CommitArtifactRequest):
                    artifact_commits.append(event.artifact_id)
                elif isinstance(event, EventFinish):
                    finished = True
                    break
                elif isinstance(event, UploadRequest):
                    # Otherwise, it's file changed, so add it to the pending batch.
                    batch.append(event)
                else:
                    raise Exception('invalid event %s' % event)

            if batch:
                paths = [e.path for e in batch]
                checksums = self._pool.imap(wandb.util.md5_file, paths, chunksize=5)

                file_specs = []
                for e, checksum in zip(batch, checksums):
                    file_specs.append({
                        'name': e.save_name, 'artifactVersionID': e.artifact_id, 'fingerprint': checksum})
                result = self._api.prepare_files(file_specs)

                for e, file_spec in zip(batch, file_specs):
                    response_file = result[e.save_name]
                    if file_spec['fingerprint'] == response_file['fingerprint']:
                        try:
                            size = os.path.getsize(e.path)
                        except OSError:
                            size = 0
                        self._progress[e.save_name] = {
                            'deduped': True,
                            'total': size,
                            'uploaded': size,
                            'failed': False
                        }
                    else:
                        start_upload_event = EventStartUploadJob(
                            e.path, e.save_name)
                        self._event_queue.put(start_upload_event)
                batch = []

            for artifact_id in artifact_commits:
                self._api.commit_artifact_version(artifact_id)

            # And stop the infinite loop if we've finished
            if finished:
                self._event_queue.put(EventFinish())
                break

    def _process_event(self, event):
        # print('EVENT %s %s' % (len(self._running_jobs), len(self._pending_jobs)))
        if isinstance(event, EventJobDone):
            job = event.job
            job.join()
            self._running_jobs.pop(job.save_name)
            # If we have any pending jobs, start one now
            if self._pending_jobs:
                event = self._pending_jobs.pop(0)
                self._start_upload_job(event)
        elif isinstance(event, EventStartUploadJob):
            if len(self._running_jobs) == self._max_jobs:
                self._pending_jobs.append(event)
            else:
                self._start_upload_job(event)
        else:
            raise Exception('Programming error: unhandled event')

    def _start_upload_job(self, event):
        if not isinstance(event, EventStartUploadJob):
            raise Exception('Programming error: invalid event')

        # Operations on a single backend file must be serialized. if
        # we're already uploading this file, put the event on the
        # end of the queue
        if event.save_name in self._running_jobs:
            self._pending_jobs.append(event)
            return

        # Start it.
        self._last_job_started_at = time.time()
        job = UploadJob(self._event_queue, self._progress, self._api,
                        event.save_name, event.path)
        self._running_jobs[event.save_name] = job
        job.start()

    def file_changed(self, save_name, path, artifact_id):
        """Tell the file pusher that a file's changed and should be uploaded.

        Arguments:
            save_name: string logical location of the file relative to the run
                directory.
            path: actual string path of the file to upload on the filesystem.
        """
        # Tests in linux were failing because wandb-events.jsonl didn't exist
        if not os.path.exists(path) or not os.path.isfile(path):
            return
        if os.path.getsize(path) == 0:
            return

        event = UploadRequest(path, save_name, artifact_id)
        self._checksum_queue.put(event)

    def commit_artifact(self, artifact_id):
        event = CommitArtifactRequest(artifact_id)
        self._checksum_queue.put(event)

    def finish(self):
        self._checksum_queue.put(EventFinish())

    def shutdown(self):
        self.finish()
        self._checksum_thread.join()
        self._process_thread.join()

    def is_alive(self):
        return self._checksum_thread.is_alive() or self._process_thread.is_alive()
