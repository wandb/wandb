import logging
import os
import fnmatch
import queue
import time

from wandb import util
import glob

wd_polling = util.vendor_import("watchdog.observers.polling")
wd_events = util.vendor_import("watchdog.events")

logger = logging.getLogger(__name__)


class FileEventHandler:
    def __init__(self, file_path, save_name, api, file_pusher, *args, **kwargs):
        self.file_path = file_path
        # Convert windows paths to unix paths
        save_name = util.to_forward_slash_path(save_name)
        self.save_name = save_name
        self._file_pusher = file_pusher
        self._last_sync = None
        self._api = api

    @property
    def synced(self):
        return self._last_sync == os.path.getmtime(self.file_path)

    @property
    def policy(self):
        raise NotImplementedError

    def on_modified(self, force=False):
        pass

    def on_renamed(self, new_path, new_name):
        self.file_path = new_path
        self.save_name = new_name
        self.on_modified()

    def finish(self):
        self.on_modified(force=True)


class PolicyIgnore(FileEventHandler):
    @property
    def policy(self):
        return "ignore"


class PolicyNow(FileEventHandler):
    """This policy only uploads files now"""

    def on_modified(self, force=False):
        # only upload if we've never uploaded or when .save is called
        if self._last_sync is None or force:
            self._file_pusher.file_changed(self.save_name, self.file_path)
            self._last_sync = os.path.getmtime(self.file_path)

    def finish(self):
        pass

    @property
    def policy(self):
        return "now"


class PolicyEnd(FileEventHandler):
    """This policy only updates at the end of the run"""

    # TODO: make sure we call this
    def finish(self):
        # We use copy=False to avoid possibly expensive copies, and because
        # user files shouldn't still be changing at the end of the run.
        self._last_sync = os.path.getmtime(self.file_path)
        self._file_pusher.file_changed(self.save_name, self.file_path, copy=False)

    @property
    def policy(self):
        return "end"


class PolicyLive(FileEventHandler):
    """This policy will upload files every RATE_LIMIT_SECONDS as it
    changes throttling as the size increases"""

    TEN_MB = 10000000
    HUNDRED_MB = 100000000
    ONE_GB = 1000000000
    RATE_LIMIT_SECONDS = 15
    # Wait to upload until size has increased 20% from last upload
    RATE_LIMIT_SIZE_INCREASE = 1.2

    def __init__(self, file_path, save_name, api, file_pusher, *args, **kwargs):
        super().__init__(file_path, save_name, api, file_pusher, *args, **kwargs)
        self._last_uploaded_time = None
        self._last_uploaded_size = 0

    @property
    def current_size(self):
        return os.path.getsize(self.file_path)

    def min_wait_for_size(self, size):
        if self.current_size < self.TEN_MB:
            return 60
        elif self.current_size < self.HUNDRED_MB:
            return 5 * 60
        elif self.current_size < self.ONE_GB:
            return 10 * 60
        else:
            return 20 * 60

    def should_update(self):
        if self._last_uploaded_time:
            # Check rate limit by time elapsed
            time_elapsed = time.time() - self._last_uploaded_time
            # if more than 15 seconds has passed potentially upload it
            if time_elapsed < self.RATE_LIMIT_SECONDS:
                return False

            # Check rate limit by size increase
            if float(self._last_uploaded_size) > 0:
                size_increase = self.current_size / float(self._last_uploaded_size)
                if size_increase < self.RATE_LIMIT_SIZE_INCREASE:
                    return False
            return time_elapsed > self.min_wait_for_size(self.current_size)

        # if the file has never been uploaded, we'll upload it
        return True

    def on_modified(self, force=False):
        if self.current_size == 0:
            return 0
        if not self.synced and self.should_update():
            self.save_file()
        # if the run is finished, or wandb.save is called explicitly save me
        elif force and not self.synced:
            self.save_file()

    def save_file(self):
        self._last_sync = os.path.getmtime(self.file_path)
        self._last_uploaded_time = time.time()
        self._last_uploaded_size = self.current_size
        self._file_pusher.file_changed(self.save_name, self.file_path)

    @property
    def policy(self):
        return "live"


class DirWatcher:
    def __init__(self, settings, api, file_pusher, file_dir=None):
        self._api = api
        self._file_count = 0
        self._dir = file_dir or settings.files_dir
        self._settings = settings
        self._user_file_policies = {"end": set(), "live": set(), "now": set()}
        self._file_pusher = file_pusher
        self._file_event_handlers = {}
        self._file_observer = wd_polling.PollingObserver()
        self._file_observer.schedule(
            self._per_file_event_handler(), self._dir, recursive=True
        )
        self._file_observer.start()
        logger.info("watching files in: %s", settings.files_dir)

    @property
    def emitter(self):
        try:
            return next(iter(self._file_observer.emitters))
        except StopIteration:
            return None

    def update_policy(self, path, policy):
        self._user_file_policies[policy].add(path)
        for src_path in glob.glob(os.path.join(self._dir, path)):
            save_name = os.path.relpath(src_path, self._dir)
            feh = self._get_file_event_handler(src_path, save_name)
            # handle the case where the policy changed
            if feh.policy != policy:
                try:
                    del self._file_event_handlers[save_name]
                except KeyError:
                    # TODO: probably should do locking, but this handles moved files for now
                    pass
                feh = self._get_file_event_handler(src_path, save_name)
            feh.on_modified(force=True)

    def _per_file_event_handler(self):
        """Create a Watchdog file event handler that does different things for every file"""
        file_event_handler = wd_events.PatternMatchingEventHandler()
        file_event_handler.on_created = self._on_file_created
        file_event_handler.on_modified = self._on_file_modified
        file_event_handler.on_moved = self._on_file_moved
        file_event_handler._patterns = [os.path.join(self._dir, os.path.normpath("*"))]
        # Ignore hidden files/folders
        #  TODO: what other files should we skip?
        file_event_handler._ignore_patterns = [
            "*.tmp",
            "*.wandb",
            "wandb-summary.json",
            os.path.join(self._dir, ".*"),
            os.path.join(self._dir, "*/.*"),
        ]
        # TODO: pipe in actual settings
        for glb in self._settings.ignore_globs:
            file_event_handler._ignore_patterns.append(os.path.join(self._dir, glb))

        return file_event_handler

    def _on_file_created(self, event):
        logger.info("file/dir created: %s", event.src_path)
        if os.path.isdir(event.src_path):
            return None
        self._file_count += 1
        # We do the directory scan less often as it grows
        if self._file_count % 100 == 0:
            emitter = self.emitter
            if emitter:
                emitter._timeout = int(self._file_count / 100) + 1
        save_name = os.path.relpath(event.src_path, self._dir)
        self._get_file_event_handler(event.src_path, save_name).on_modified()

    def _on_file_modified(self, event):
        logger.info("file/dir modified: %s", event.src_path)
        if os.path.isdir(event.src_path):
            return None
        save_name = os.path.relpath(event.src_path, self._dir)
        self._get_file_event_handler(event.src_path, save_name).on_modified()

    def _on_file_moved(self, event):
        # TODO: test me...
        logger.info("file/dir moved: %s -> %s", event.src_path, event.dest_path)
        if os.path.isdir(event.dest_path):
            return None
        old_save_name = os.path.relpath(event.src_path, self._dir)
        new_save_name = os.path.relpath(event.dest_path, self._dir)

        # We have to move the existing file handler to the new name
        handler = self._get_file_event_handler(event.src_path, old_save_name)
        self._file_event_handlers[new_save_name] = handler
        del self._file_event_handlers[old_save_name]

        handler.on_renamed(event.dest_path, new_save_name)

    def _get_file_event_handler(self, file_path, save_name):
        """Get or create an event handler for a particular file.

        file_path: the file's actual path
        save_name: its path relative to the run directory (aka the watch directory)
        """
        if save_name not in self._file_event_handlers:
            # TODO: we can use PolicyIgnore if there are files we never want to sync
            if "tfevents" in save_name or "graph.pbtxt" in save_name:
                self._file_event_handlers[save_name] = PolicyLive(
                    file_path, save_name, self._api, self._file_pusher
                )
            else:
                Handler = PolicyEnd
                for policy, globs in self._user_file_policies.items():
                    if policy == "end":
                        continue
                    # Convert set to list to avoid RuntimeError's
                    # TODO: we may need to add locks
                    for g in list(globs):
                        paths = glob.glob(os.path.join(self._dir, g))
                        if any(save_name in p for p in paths):
                            if policy == "live":
                                Handler = PolicyLive
                            elif policy == "now":
                                Handler = PolicyNow
                self._file_event_handlers[save_name] = Handler(
                    file_path, save_name, self._api, self._file_pusher
                )
        return self._file_event_handlers[save_name]

    def finish(self):
        logger.info("shutting down directory watcher")
        try:
            # avoid hanging if we crashed before the observer was started
            if self._file_observer.is_alive():
                # rather unfortunatly we need to manually do a final scan of the dir
                # with `queue_events`, then iterate through all events before stopping
                # the observer to catch all files written.  First we need to prevent the
                # existing thread from consuming our final events, then we process them
                self._file_observer._timeout = 0
                self._file_observer._stopped_event.set()
                self._file_observer.join()
                self.emitter.queue_events(0)
                while True:
                    try:
                        self._file_observer.dispatch_events(
                            self._file_observer.event_queue, 0
                        )
                    except queue.Empty:
                        break
                # Calling stop unschedules any inflight events so we handled them above
                self._file_observer.stop()
        # TODO: py2 TypeError: PyCObject_AsVoidPtr called with null pointer
        except TypeError:
            pass
        # TODO: py3 SystemError: <built-in function stop> returned an error
        except SystemError:
            pass

        # Ensure we've at least noticed every file in the run directory. Sometimes
        # we miss things because asynchronously watching filesystems isn't reliable.
        logger.info("scan: %s", self._dir)

        for dirpath, _, filenames in os.walk(self._dir):
            for fname in filenames:
                file_path = os.path.join(dirpath, fname)
                save_name = os.path.relpath(file_path, self._dir)
                ignored = False
                for glb in self._settings.ignore_globs:
                    if len(fnmatch.filter([save_name], glb)) > 0:
                        ignored = True
                        logger.info("ignored: %s matching glob %s", save_name, glb)
                        break
                if ignored:
                    continue
                logger.info("scan save: %s %s", file_path, save_name)
                self._get_file_event_handler(file_path, save_name).finish()
