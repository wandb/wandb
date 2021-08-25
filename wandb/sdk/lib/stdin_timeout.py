# --disable-error-code attr-defined
import sys
from typing import Optional

from wandb.errors import InputTimeoutError

DEFAULT_TIMEOUT = None
INTERVAL = 0.1
TIMEOUT_CODE = -2

# telnet convention
SP = " "
CR = "\r"
LF = "\n"
CRLF = CR + LF


def echo(prompt: str) -> None:
    sys.stdout.write(prompt)
    sys.stdout.flush()


def posix_stdin_timeout(
    prompt: str = "", timeout: Optional[float] = DEFAULT_TIMEOUT, timeout_log: str = "",
) -> str:
    echo(prompt)
    sel = selectors.DefaultSelector()
    sel.register(sys.stdin, selectors.EVENT_READ)
    keys_and_events = sel.select(timeout)
    if keys_and_events:
        key, _ = keys_and_events[0]
        return key.fileobj.readline().rstrip(LF)  # type: ignore[union-attr]
    else:
        echo(LF)
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
        raise InputTimeoutError(timeout_log)  # type: ignore[no-untyped-call]


def windows_stdin_timeout(
    prompt: str = "", timeout: Optional[float] = DEFAULT_TIMEOUT, timeout_log: str = "",
) -> str:
    echo(prompt)
    if not timeout:
        return input()

    begin = time.monotonic()
    end = begin + timeout
    line = ""
    while time.monotonic() < end:
        if msvcrt.kbhit():  # type: ignore[attr-defined]
            c = msvcrt.getwche()  # type: ignore[attr-defined]
            if c in (CR, LF):
                echo(CRLF)
                return line
            if c == "\b":
                cover = SP * len(prompt + line[:-1] + SP)
                echo("".join([CR, cover, CR, prompt, line[:-1]]))
            else:
                line += c
        time.sleep(INTERVAL)
    echo(CRLF)
    raise InputTimeoutError(timeout_log)  # type: ignore[no-untyped-call]


try:
    import msvcrt
    import time

    stdin_timeout = windows_stdin_timeout
except ImportError:
    import selectors
    import termios

    stdin_timeout = posix_stdin_timeout
