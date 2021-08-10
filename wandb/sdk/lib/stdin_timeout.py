import sys

from wandb.errors import InputTimeoutError

DEFAULT_TIMEOUT = None
INTERVAL = 0.1
TIMEOUT_CODE = -2

# telnet convention
SP = " "
CR = "\r"
LF = "\n"
CRLF = CR + LF


def echo(prompt):
    sys.stdout.write(prompt)
    sys.stdout.flush()


def posix_stdin_timeout(prompt="", timeout=DEFAULT_TIMEOUT, timeout_log=""):
    echo(prompt)
    sel = selectors.DefaultSelector()
    sel.register(sys.stdin, selectors.EVENT_READ)
    keys_and_events = sel.select(timeout)

    if keys_and_events:
        key, _ = keys_and_events[0]
        return key.fileobj.readline().rstrip(LF)
    else:
        echo(LF)
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
        raise InputTimeoutError(timeout_log)


def windows_stdin_timeout(prompt="", timeout=DEFAULT_TIMEOUT, timeout_log=""):
    echo(prompt)
    begin = time.monotonic()
    end = begin + timeout
    line = ""

    while time.monotonic() < end:
        if msvcrt.kbhit():
            c = msvcrt.getwche()
            if c in (CR, LF):
                echo(CRLF)
                return line
            if c == "\b":
                line = line[:-1]
                cover = SP * len(prompt + line + SP)
                echo("".join([CR, cover, CR, prompt, line]))
            else:
                line += c
        time.sleep(INTERVAL)

    echo(CRLF)
    raise InputTimeoutError(timeout_log)


try:
    import msvcrt

except ImportError:
    import selectors
    import termios

    stdin_timeout = posix_stdin_timeout

else:
    import time

    stdin_timeout = windows_stdin_timeout
