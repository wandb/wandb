import argparse
import fcntl
import os
import sys
import termios

from wandb.errors.term import terminput

if __name__ == "__main__":
    # Tell the pseudoterminal to which stdin is attached to control
    # this process, so that it can implement Ctrl+C and so on.
    os.setsid()
    fcntl.ioctl(sys.stdin, termios.TIOCSCTTY)

    parser = argparse.ArgumentParser()
    parser.add_argument("--hide", action="store_true")
    parser.add_argument("--timeout")
    args = parser.parse_args()

    hide = bool(args.hide)
    if timeout_str := args.timeout:
        timeout = float(timeout_str)
    else:
        timeout = None

    try:
        result = terminput("PROMPT: ", hide=hide, timeout=timeout)
    except TimeoutError:
        sys.stderr.write("TIMEOUT!\n")
    except KeyboardInterrupt:
        sys.stderr.write("INTERRUPT!\n")
    else:
        sys.stderr.write(f"Got result: {result}\n")
        sys.stderr.write("DONE\n")
