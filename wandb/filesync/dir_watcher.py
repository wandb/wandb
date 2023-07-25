import abc
import fnmatch
import glob
import logging
import os
import queue
import time
from typing import TYPE_CHECKING, Any, Mapping, MutableMapping, MutableSet, Optional

from wandb import util
from wandb.sdk.interface.interface import GlobStr
from wandb.sdk.lib.paths import LogicalPath

if TYPE_CHECKING:
    import wandb.vendor.watchdog_0_9_0.observers.api as wd_api
    import wandb.vendor.watchdog_0_9_0.observers.polling as wd_polling
    import wandb.vendor.watchdog_0_9_0.watchdog.events as wd_events
    from wandb.sdk.interface.interface import PolicyName
    from wandb.sdk.internal.file_pusher import FilePusher
    from wandb.sdk.internal.settings_static import SettingsStatic
else:
    wd_polling = util.vendor_import("wandb_watchdog.observers.polling")
    wd_events = util.vendor_import("wandb_watchdog.events")

PathStr = str  # TODO(spencerpearson): would be nice to use Path here


logger = logging.getLogger(__name__)


class FileEventHandler(abc.ABC):
    def __init__(
        self,
        file_path: PathStr,
        save_name: LogicalPath,
        file_pusher: "FilePusher",
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self.file_path = file_path
        # Convert windows paths to unix paths
        self.save_name = LogicalPath(save_name)
        self._file_pusher = file_pusher
        self._last_sync: Optional[float] = None

    @property
    @abc.abstractmethod
    def policy(self) -> "PolicyName":
        raise NotImplementedError

    @abc.abstractmethod
    def on_modified(self, force: bool = False) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def finish(self) -> None:
        raise NotImplementedError

    def on_renamed(self, new_path: PathStr, new_name: LogicalPath) -> None:
        self.file_path = new_path
        self.save_name = new_name
        self.on_modified()


class PolicyNow(FileEventHandler):
    """This policy only uploads files now."""

    def on_modified(self, force: bool = False) -> None:
        # only upload if we've never uploaded or when .save is called
        if self._last_sync is None or force:
            self._file_pusher.file_changed(self.save_name, self.file_path)
            self._last_sync = os.path.getmtime(self.file_path)

    def finish(self) -> None:
        pass

    @property
    def policy(self) -> "PolicyName":
        return "now"


class PolicyEnd(FileEventHandler):
    """This policy only updates at the end of the run."""

    def on_modified(self, force: bool = False) -> None:
        pass

    # TODO: make sure we call this
    def finish(self) -> None:
        # We use copy=False to avoid possibly expensive copies, and because
        # user files shouldn't still be changing at the end of the run.
        self._last_sync = os.path.getmtime(self.file_path)
        self._file_pusher.file_changed(self.save_name, self.file_path, copy=False)

    @property
    def policy(self) -> "PolicyName":
        return "end"


class PolicyLive(FileEventHandler):
    """Event handler that uploads respecting throttling.

    Uploads files every RATE_LIMIT_SECONDS, which changes as the size increases to deal
    with throttling.
    """

    RATE_LIMIT_SECONDS = 15
    unit_dict = dict(util.POW_10_BYTES)
    # Wait to upload until size has increased 20% from last upload
    RATE_LIMIT_SIZE_INCREASE = 1.2

    def __init__(
        self,
        file_path: PathStr,
        save_name: LogicalPath,
        file_pusher: "FilePusher",
        settings: Optional["SettingsStatic"] = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(file_path, save_name, file_pusher, *args, **kwargs)
        self._last_uploaded_time: Optional[float] = None
        self._last_uploaded_size: int = 0
        if settings is not None:
            if settings._live_policy_rate_limit is not None:
                self.RATE_LIMIT_SECONDS = settings._live_policy_rate_limit
            self._min_wait_time: Optional[float] = settings._live_policy_wait_time
        else:
            self._min_wait_time = None

    @property
    def current_size(self) -> int:
        return os.path.getsize(self.file_path)

    @classmethod
    def min_wait_for_size(cls, size: int) -> float:
        if size < 10 * cls.unit_dict["MB"]:
            return 60
        elif size < 100 * cls.unit_dict["MB"]:
            return 5 * 60
        elif size < cls.unit_dict["GB"]:
            return 10 * 60
        else:
            return 20 * 60

    def should_update(self) -> bool:
        if self._last_uploaded_time is not None:
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
            return time_elapsed > (
                self._min_wait_time or self.min_wait_for_size(self.current_size)
            )

        # if the file has never been uploaded, we'll upload it
        return True

    def on_modified(self, force: bool = False) -> None:
        if self.current_size == 0:
            return
        if self._last_sync == os.path.getmtime(self.file_path):
            return
        if force or self.should_update():
            self.save_file()

    def save_file(self) -> None:
        self._last_sync = os.path.getmtime(self.file_path)
        self._last_uploaded_time = time.time()
        self._last_uploaded_size = self.current_size
        self._file_pusher.file_changed(self.save_name, self.file_path)

    def finish(self) -> None:
        self.on_modified(force=True)

    @property
    def policy(self) -> "PolicyName":
        return "live"


class DirWatcher:
    def __init__(
        self,
        settings: "SettingsStatic",
        file_pusher: "FilePusher",
        file_dir: Optional[PathStr] = None,
    ) -> None:
        self._file_count = 0
        self._dir = file_dir or settings.files_dir
        self._settings = settings
        self._savename_file_policies: MutableMapping[LogicalPath, PolicyName] = {}
        self._user_file_policies: Mapping[PolicyName, MutableSet[GlobStr]] = {
            "end": set(),
            "live": set(),
            "now": set(),
        }
        self._file_pusher = file_pusher
        self._file_event_handlers: MutableMapping[LogicalPath, FileEventHandler] = {}
        self._file_observer = wd_polling.PollingObserver()
        self._file_observer.schedule(
            self._per_file_event_handler(), self._dir, recursive=True
        )
        self._file_observer.start()
        logger.info("watching files in: %s", settings.files_dir)

    @property
    def emitter(self) -> Optional["wd_api.EventEmitter"]:
        try:
            return next(iter(self._file_observer.emitters))
        except StopIteration:
            return None

    def update_policy(self, path: GlobStr, policy: "PolicyName") -> None:
        # When we're dealing with one of our own media files, there's no need
        # to store the policy in memory.  _get_file_event_handler will always
        # return PolicyNow.  Using the path makes syncing historic runs much
        # faster if the name happens to include glob escapable characters.  In
        # the future we may add a flag to "files" records that indicates it's
        # policy is not dynamic and doesn't need to be stored / checked.
        save_name = LogicalPath(
            os.path.relpath(os.path.join(self._dir, path), self._dir)
        )
        if save_name.startswith("media/"):
            pass
        elif path == glob.escape(path):
            self._savename_file_policies[save_name] = policy
        else:
            self._user_file_policies[policy].add(path)
        for src_path in glob.glob(os.path.join(self._dir, path)):
            save_name = LogicalPath(os.path.relpath(src_path, self._dir))
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

    def _per_file_event_handler(self) -> "wd_events.FileSystemEventHandler":
        """Create a Watchdog file event handler that does different things for every file."""
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
        for glb in self._settings.ignore_globs:
            file_event_handler._ignore_patterns.append(os.path.join(self._dir, glb))

        return file_event_handler

    def _on_file_created(self, event: "wd_events.FileCreatedEvent") -> None:
        logger.info("file/dir created: %s", event.src_path)
        if os.path.isdir(event.src_path):
            return None
        self._file_count += 1
        # We do the directory scan less often as it grows
        if self._file_count % 100 == 0:
            emitter = self.emitter
            if emitter:
                emitter._timeout = int(self._file_count / 100) + 1
        save_name = LogicalPath(os.path.relpath(event.src_path, self._dir))
        self._get_file_event_handler(event.src_path, save_name).on_modified()

    # TODO(spencerpearson): this pattern repeats so many times we should have a method/function for it
    # def _save_name(self, path: PathStr) -> LogicalPath:
    #     return LogicalPath(os.path.relpath(path, self._dir))

    def _on_file_modified(self, event: "wd_events.FileModifiedEvent") -> None:
        logger.info(f"file/dir modified: { event.src_path}")
        if os.path.isdir(event.src_path):
            return None
        save_name = LogicalPath(os.path.relpath(event.src_path, self._dir))
        self._get_file_event_handler(event.src_path, save_name).on_modified()

    def _on_file_moved(self, event: "wd_events.FileMovedEvent") -> None:
        # TODO: test me...
        logger.info(f"file/dir moved: {event.src_path} -> {event.dest_path}")
        if os.path.isdir(event.dest_path):
            return None
        old_save_name = LogicalPath(os.path.relpath(event.src_path, self._dir))
        new_save_name = LogicalPath(os.path.relpath(event.dest_path, self._dir))

        # We have to move the existing file handler to the new name
        handler = self._get_file_event_handler(event.src_path, old_save_name)
        self._file_event_handlers[new_save_name] = handler
        del self._file_event_handlers[old_save_name]

        handler.on_renamed(event.dest_path, new_save_name)

    def _get_file_event_handler(
        self, file_path: PathStr, save_name: LogicalPath
    ) -> FileEventHandler:
        """Get or create an event handler for a particular file.

        file_path: the file's actual path
        save_name: its path relative to the run directory (aka the watch directory)
        """
        # Always return PolicyNow for any of our media files.
        if save_name.startswith("media/"):
            return PolicyNow(file_path, save_name, self._file_pusher, self._settings)
        if save_name not in self._file_event_handlers:
            # TODO: we can use PolicyIgnore if there are files we never want to sync
            if "tfevents" in save_name or "graph.pbtxt" in save_name:
                self._file_event_handlers[save_name] = PolicyLive(
                    file_path, save_name, self._file_pusher, self._settings
                )
            elif save_name in self._savename_file_policies:
                policy_name = self._savename_file_policies[save_name]
                make_handler = (
                    PolicyLive
                    if policy_name == "live"
                    else PolicyNow
                    if policy_name == "now"
                    else PolicyEnd
                )
                self._file_event_handlers[save_name] = make_handler(
                    file_path, save_name, self._file_pusher, self._settings
                )
            else:
                make_handler = PolicyEnd
                for policy, globs in self._user_file_policies.items():
                    if policy == "end":
                        continue
                    # Convert set to list to avoid RuntimeError's
                    # TODO: we may need to add locks
                    for g in list(globs):
                        paths = glob.glob(os.path.join(self._dir, g))
                        if any(save_name in p for p in paths):
                            if policy == "live":
                                make_handler = PolicyLive
                            elif policy == "now":
                                make_handler = PolicyNow
                self._file_event_handlers[save_name] = make_handler(
                    file_path, save_name, self._file_pusher, self._settings
                )
        return self._file_event_handlers[save_name]

    def finish(self) -> None:
        logger.info("shutting down directory watcher")
        try:
            # avoid hanging if we crashed before the observer was started
            if self._file_observer.is_alive():
                # rather unfortunately we need to manually do a final scan of the dir
                # with `queue_events`, then iterate through all events before stopping
                # the observer to catch all files written.  First we need to prevent the
                # existing thread from consuming our final events, then we process them
                self._file_observer._timeout = 0
                self._file_observer._stopped_event.set()
                self._file_observer.join()
                self.emitter.queue_events(0)  # type: ignore[union-attr]
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
                save_name = LogicalPath(os.path.relpath(file_path, self._dir))
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
