import os
import time
from pathlib import Path

import pytest
from wandb.sdk.lib.filesystem import (
    mkdir_exists_ok,
)


def write_pause(path, content):
    """Append `content` to the file at path, flush the write, and wait 10ms.

    This ensures that file modification times are different for successive writes.
    """
    mode = "ab" if isinstance(path, bytes) else "a"
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode) as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    time.sleep(0.01)


@pytest.mark.parametrize("pathtype", [Path, str, bytes])
def test_mkdir_exists_ok_pathtypes(tmp_path, pathtype):
    """Test that mkdir_exists_ok works with all path-like objects."""
    new_dir = tmp_path / "new"
    mkdir_exists_ok(pathtype(new_dir))
    assert new_dir.is_dir()
