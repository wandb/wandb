"""Utility to send an interrupt (Ctrl+C) signal to the main thread.

This is necessary because Windows and POSIX use different models for Ctrl+C
interrupts.
"""

import platform
import signal
import threading


def interrupt_main():
    """Interrupt the main Python thread with a SIGINT signal.

    In POSIX, signal.pthread_kill() is the most reliable way to send a signal
    to the main thread.

    os.kill() is often recommended, but it isn't guaranteed to deliver the
    signal to the main OS thread. Likewise, signal.raise_signal() delivers
    the signal to the current thread in POSIX. The issue is that if any other
    thread receives the signal, Python will set an internal flag and process it
    on the main thread at the next opportunity. If the main thread is executing
    C code or is blocked on a syscall (e.g. time.sleep(999999)) the signal
    handler won't execute until that's done---i.e. Python won't preempt the OS
    thread on its own.

    On Windows, pthread_kill is not available and os.kill() ignores its
    second argument and always kills the process. However,
    signal.raise_signal() does the right thing.
    """
    if platform.system() == "Windows":
        signal.raise_signal(signal.SIGINT)
    else:
        signal.pthread_kill(
            threading.main_thread().ident,
            signal.SIGINT,
        )
