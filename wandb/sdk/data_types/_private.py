import atexit
import tempfile
import threading
from typing import Optional

# Staging directory, so we can encode raw data into files, then hash them before
# we put them into the Run directory to be uploaded.
MEDIA_TMP: Optional[tempfile.TemporaryDirectory] = None
media_tmp_lock = threading.Lock()


def _get_media_tmp_dir() -> tempfile.TemporaryDirectory:
    global MEDIA_TMP

    if MEDIA_TMP:
        return MEDIA_TMP

    with media_tmp_lock:
        # Check again in case another thread created it while we were waiting
        if MEDIA_TMP:
            return MEDIA_TMP

        MEDIA_TMP = tempfile.TemporaryDirectory("wandb-media")
        atexit.register(MEDIA_TMP.cleanup)  # Register the cleanup only once
        return MEDIA_TMP


def _cleanup_media_tmp_dir() -> None:
    atexit.register(MEDIA_TMP.cleanup)
