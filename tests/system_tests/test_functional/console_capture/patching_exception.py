"""Exits with code 0 if an exception patching stdout is rethrown."""

import io
import sys
from typing import TextIO


class _TestError(Exception):
    pass


class MyStdout(io.TextIOBase):
    def __init__(self, delegate: TextIO) -> None:
        self._delegate = delegate

    def __setattr__(self, name, value):
        if name == "write":
            raise _TestError()
        return super().__setattr__(name, value)


if __name__ == "__main__":
    sys.stdout = MyStdout(sys.stdout)

    # This will attempt to overwrite `sys.stdout.write` on import,
    # which will raise an error that must not be propagated.
    from wandb.sdk.lib import console_capture

    try:
        console_capture.capture_stdout(lambda *unused: None)
    except console_capture.CannotCaptureConsoleError as e:
        if e.__cause__ and isinstance(e.__cause__, _TestError):
            print("[stdout] Caught _TestError!", file=sys.stderr)
        else:
            print(
                "[stdout] Caught error, but its cause is not _TestError!",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        print("[stdout] No error!", file=sys.stderr)
        sys.exit(1)

    try:
        console_capture.capture_stderr(lambda *unused: None)
    except console_capture.CannotCaptureConsoleError as e:
        if e.__cause__ and isinstance(e.__cause__, _TestError):
            print("[stderr] Caught _TestError!", file=sys.stderr)
        else:
            print(
                "[stderr] Caught error, but its cause is not _TestError!",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        print("[stderr] No error!", file=sys.stderr)
        sys.exit(1)
