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


def _echo(prompt: str) -> None:
    sys.stdout.write(prompt)
    sys.stdout.flush()


def _posix_timed_input(prompt: str, timeout: float) -> str:
    _echo(prompt)
    sel = selectors.DefaultSelector()
    sel.register(sys.stdin, selectors.EVENT_READ, data=sys.stdin.readline)
    events = sel.select(timeout=timeout)

    for key, _ in events:
        input_callback = key.data
        input_data: str = input_callback()
        if not input_data:  # end-of-file - treat as timeout
            raise TimeoutError
        return input_data.rstrip(LF)

    _echo(LF)
    termios.tcflush(sys.stdin, termios.TCIFLUSH)
    raise TimeoutError


def _windows_timed_input(prompt: str, timeout: float) -> str:
    interval = 0.1

    _echo(prompt)
    begin = time.monotonic()
    end = begin + timeout
    line = ""

    while time.monotonic() < end:
        if msvcrt.kbhit():  # type: ignore[attr-defined]
            c = msvcrt.getwche()  # type: ignore[attr-defined]
            if c in (CR, LF):
                _echo(CRLF)
                return line
            if c == "\003":
                raise KeyboardInterrupt
            if c == "\b":
                line = line[:-1]
                cover = SP * len(prompt + line + SP)
                _echo("".join([CR, cover, CR, prompt, line]))
            else:
                line += c
        time.sleep(interval)

    _echo(CRLF)
    raise TimeoutError


def _jupyter_timed_input(prompt: str, timeout: float) -> str:
    clear = True
    try:
        from IPython.core.display import clear_output  # type: ignore
    except ImportError:
        clear = False
        wandb.termwarn(
            "Unable to clear output, can't import clear_output from ipython.core"
        )

    _echo(prompt)

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
    prompt: str, timeout: float, show_timeout: bool = True, jupyter: bool = False
) -> str:
    """Behaves like builtin `input()` but adds timeout.

    Args:
        prompt (str): Prompt to output to stdout.
        timeout (float): Timeout to wait for input.
        show_timeout (bool): Show timeout in prompt
        jupyter (bool): If True, use jupyter specific code.

    Raises:
        TimeoutError: exception raised if timeout occurred.
    """
    if show_timeout:
        prompt = f"{prompt}({timeout:.0f} second timeout) "
    if jupyter:
        return _jupyter_timed_input(prompt=prompt, timeout=timeout)

    return _timed_input(prompt=prompt, timeout=timeout)


try:
    import msvcrt
except ImportError:
    import selectors
    import termios

    _timed_input = _posix_timed_input
else:
    import time

    _timed_input = _windows_timed_input
