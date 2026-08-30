import atexit
import tempfile
import threading


class _LazyTemporaryDirectory:
    def __init__(self, suffix: str) -> None:
        self._suffix = suffix
        self._directory: tempfile.TemporaryDirectory | None = None
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        with self._lock:
            if self._directory is None:
                self._directory = tempfile.TemporaryDirectory(self._suffix)
            return self._directory.name

    def cleanup(self) -> None:
        with self._lock:
            if self._directory is not None:
                self._directory.cleanup()


# Staging directory, so we can encode raw data into files, then hash them before
# we put them into the Run directory to be uploaded.
MEDIA_TMP = _LazyTemporaryDirectory("wandb-media")


def _cleanup_media_tmp_dir() -> None:
    atexit.register(MEDIA_TMP.cleanup)
