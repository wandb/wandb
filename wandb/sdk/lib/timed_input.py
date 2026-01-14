"""timed_input: add a timeout to standard input.

Approach was inspired by: https://github.com/johejo/inputimeout
"""

import sys
import threading

import wandb

SP = " "
CR = "\r"
LF = "\n"
CRLF = CR + LF


def _echo(prompt: str, *, err: bool) -> None:
    stream = sys.stderr if err else sys.stdout
    stream.write(prompt)
    stream.flush()


def _posix_timed_input(prompt: str, timeout: float, err: bool) -> str:
    _echo(prompt, err=err)
    sel = selectors.DefaultSelector()
    sel.register(sys.stdin, selectors.EVENT_READ, data=sys.stdin.readline)
    events = sel.select(timeout=timeout)

    for key, _ in events:
        input_callback = key.data
        input_data: str = input_callback()
        if not input_data:  # end-of-file - treat as timeout
            raise TimeoutError
        return input_data.rstrip(LF)

    _echo(LF, err=err)
    termios.tcflush(sys.stdin, termios.TCIFLUSH)
    raise TimeoutError


def _windows_timed_input(prompt: str, timeout: float, err: bool) -> str:
    interval = 0.1

    _echo(prompt, err=err)
    begin = time.monotonic()
    end = begin + timeout
    line = ""

    while time.monotonic() < end:
        if msvcrt.kbhit():  # type: ignore[attr-defined]
            c = msvcrt.getwche()  # type: ignore[attr-defined]
            if c in (CR, LF):
                _echo(CRLF, err=err)
                return line
            if c == "\003":
                raise KeyboardInterrupt
            if c == "\b":
                line = line[:-1]
                cover = SP * len(prompt + line + SP)
                _echo("".join([CR, cover, CR, prompt, line]), err=err)
            else:
                line += c
        time.sleep(interval)

    _echo(CRLF, err=err)
    raise TimeoutError


def _jupyter_timed_input(prompt: str, timeout: float, err: bool) -> str:
    clear = True
    try:
        from IPython.core.display import clear_output  # type: ignore
    except ImportError:
        clear = False
        wandb.termwarn(
            "Unable to clear output, can't import clear_output from ipython.core"
        )

    _echo(prompt, err=err)

    user_inp = None
    event = threading.Event()

    def get_input() -> None:
        nonlocal user_inp
        raw = input()
        if event.is_set():
            return
        user_inp = raw

    t = threading.Thread(target=get_input)
    t.start()
    t.join(timeout)
    event.set()
    if user_inp:
        return user_inp
    if clear:
        clear_output()
    raise TimeoutError


def timed_input(
    prompt: str,
    timeout: float,
    show_timeout: bool = True,
    jupyter: bool = False,
    err: bool = False,
) -> str:
    """Behaves like builtin `input()` but adds timeout.

    Args:
        prompt: Prompt to output to stdout.
        timeout: Timeout to wait for input.
        show_timeout: Show timeout in prompt
        jupyter: If True, use jupyter specific code.
        err: If True, use stderr instead of stdout.

    Raises:
        TimeoutError: If a timeout occurred.
        KeyboardInterrupt: If the user aborted by pressing Ctrl+C.
    """
    if show_timeout:
        prompt = f"{prompt}({timeout:.0f} second timeout) "
    if jupyter:
        return _jupyter_timed_input(prompt=prompt, timeout=timeout, err=err)

    return _timed_input(prompt=prompt, timeout=timeout, err=err)


try:
    import msvcrt
except ImportError:
    import selectors
    import termios

    _timed_input = _posix_timed_input
else:
    import time

    _timed_input = _windows_timed_input
