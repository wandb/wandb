import atexit
import tempfile

# Staging directory, so we can encode raw data into files, then hash them before
# we put them into the Run directory to be uploaded.
MEDIA_TMP = tempfile.TemporaryDirectory("wandb-media")


def _cleanup_media_tmp_dir() -> None:
    atexit.register(MEDIA_TMP.cleanup)
