"""console."""

import os


def win32_redirect(stdout_slave_fd, stderr_slave_fd):
    # import win32api

    # save for later
    # fd_stdout = os.dup(1)
    # fd_stderr = os.dup(2)

    # std_out = win32api.GetStdHandle(win32api.STD_OUTPUT_HANDLE)
    # std_err = win32api.GetStdHandle(win32api.STD_ERROR_HANDLE)

    # os.dup2(stdout_slave_fd, 1)
    # os.dup2(stderr_slave_fd, 2)

    # TODO(jhr): do something about current stdout, stderr file handles
    pass


def win32_create_pipe():
    # import pywintypes
    # import win32pipe

    # sa=pywintypes.SECURITY_ATTRIBUTES()
    # sa.bInheritHandle=1

    # read_fd, write_fd = win32pipe.FdCreatePipe(sa, 0, os.O_TEXT)
    # read_fd, write_fd = win32pipe.FdCreatePipe(sa, 0, os.O_BINARY)
    read_fd, write_fd = os.pipe()
    # http://timgolden.me.uk/pywin32-docs/win32pipe__FdCreatePipe_meth.html
    # https://stackoverflow.com/questions/17942874/stdout-redirection-with-ctypes

    # f = open("testing.txt", "rb")
    # read_fd = f.fileno()

    return read_fd, write_fd
