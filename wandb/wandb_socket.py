import six
import time
import logging
import socket
from select import select
import threading

logger = logging.getLogger(__name__)


def ints2bytes(ints):
    return six.b('').join([six.int2byte(i) for i in ints])


class Server(object):
    """A simple socket server started in the user process.  It binds to a port
    assigned by the OS.  It must receive a message from the wandb process within
    5 seconds of calling connect to be established.

    Wire Protocol:
    1 => ready
    2 => done, followed by optional exitcode byte
    """

    def __init__(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind(('', 0))
        self.socket.listen(1)
        self.socket.settimeout(5.0)
        self.port = self.socket.getsockname()[1]
        self.connection = None

    def connect(self):
        self.connection, addr = self.socket.accept()
        self.connection.setblocking(False)

    def listen(self, max_seconds=30):
        """Waits to receive up to two bytes for up to max_seconds"""
        if not self.connection:
            self.connect()
        # TODO: handle errs
        conn, _, err = select([self.connection], [], [
                              self.connection], max_seconds)
        try:
            res = bytearray(self.connection.recv(2))
            if res[0] in [1, 2]:
                return True
            else:
                raise socket.error()
        except socket.error as e:
            logger.error(
                "Failed to receive valid message from wandb process within %s seconds" % max_seconds)
            return False

    def done(self, exitcode=None):
        data = [2]
        if exitcode is not None:
            data.append(exitcode)
        self.send(data)

    def send(self, data):
        orig = data
        if isinstance(data, list):
            data = ints2bytes(data)
        self.connection.sendall(data)


class Client(object):
    """Socket client used in the wandb process"""

    def __init__(self, port=None):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.settimeout(1.0)
        self.port = port
        if self.port:
            self.socket.connect(('', self.port))
            self.connected = True
        else:
            self.connected = False

    def send(self, data):
        if isinstance(data, list):
            data = ints2bytes(data)
        if self.connected:
            self.socket.sendall(data)

    def recv(self, limit):
        if self.connected:
            return bytearray(self.socket.recv(limit))
        else:
            return bytearray()

    def done(self):
        try:
            self.send([2])
        except socket.error:
            logger.warn(
                "Wandb took longer than 30 seconds and the user process finished")

    def ready(self):
        self.send([1])
