import atexit
import tempfile
import threading
from typing import Optional

media_tmp_dir_lock = threading.Lock()

# Staging directory, so we can encode raw data into files, then hash them before
# we put them into the Run directory to be uploaded.
MEDIA_TMP: Optional[tempfile.TemporaryDirectory] = None


def _get_media_tmp_dir() -> tempfile.TemporaryDirectory:
    global MEDIA_TMP

    if MEDIA_TMP:
        print("Using existing media tmpdir", MEDIA_TMP.name)
        return MEDIA_TMP

    with media_tmp_dir_lock:
        # check again in case another thread created it
        if MEDIA_TMP:
            print("Using existing media tmpdir", MEDIA_TMP.name)
            return MEDIA_TMP

        MEDIA_TMP = tempfile.TemporaryDirectory("wandb-media")
        print("Created new media tmpdir", MEDIA_TMP.name)

        # clear the tmpdir on exit
        def cleanup() -> None:
            if MEDIA_TMP:
                print("Cleaning up media tmpdir", MEDIA_TMP.name)
                MEDIA_TMP.cleanup()

        atexit.register(cleanup)

        return MEDIA_TMP
