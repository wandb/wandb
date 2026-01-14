"""Exits with code 0 if stdout and stderr callbacks are triggered.

On success, prints "I AM STDOUT" to stdout and "I AM STDERR" to stderr.
On error, prints additional text to stderr.
"""

import sys

from wandb.sdk.lib import console_capture

_got_stdout = False
_got_stderr = False


def _on_stdout(s, n):
    global _got_stdout
    _got_stdout = True


def _on_stderr(s, n):
    global _got_stderr
    _got_stderr = True


if __name__ == "__main__":
    console_capture.capture_stdout(_on_stdout)
    console_capture.capture_stderr(_on_stderr)

    sys.stdout.write("I AM STDOUT\n")
    sys.stderr.write("I AM STDERR\n")

    if not _got_stdout:
        sys.stderr.write("Didn't intercept stdout!")
        sys.exit(1)

    if not _got_stderr:
        sys.stderr.write("Didn't intercept stderr!")
        sys.exit(1)

    sys.exit(0)
