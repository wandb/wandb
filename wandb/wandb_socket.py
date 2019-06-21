import six
import time
import json
import socket
from select import select
from wandb import util
import threading


def ints2bytes(ints):
    return six.b('').join([six.int2byte(i) for i in ints])


CODE_READY = 1
CODE_DONE = 2
CODE_LAUNCH_ERROR = 100


class Server(object):
    """A simple socket server started in the user process.  It binds to a port
    assigned by the OS.

    Wire Protocol:
        JSON terminated by \0
    """

    def __init__(self, port=None):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.socket.bind(('localhost', 0))
        except OSError:
            # Handles the case of not being able to resolve localhost
            self.socket.bind(('127.0.0.1', 0))
        self.socket.listen(1)
        self.socket.settimeout(30)
        self.port = port or self.socket.getsockname()[1]
        self.connection = None

    def connect(self):
        self.connection, addr = self.socket.accept()
        self.connection.setblocking(False)

    def listen(self, max_seconds=30):
        """Waits to receive up to two bytes for up to max_seconds"""
        if not self.connection:
            self.connect()
        start = time.time()
        conn, _, err = select([self.connection], [], [
                              self.connection], max_seconds)
        try:
            if len(err) > 0:
                raise socket.error("Couldn't open socket")
            message = b''
            while True:
                if time.time() - start > max_seconds:
                    raise socket.error(
                        "Timeout of %s seconds waiting for W&B process" % max_seconds)
                res = self.connection.recv(1024)
                term = res.find(b'\0')
                if term != -1:
                    message += res[:term]
                    break
                else:
                    message += res
            message = json.loads(message.decode('utf8'))
            if message['status'] == 'done':
                return True, None
            elif message['status'] == 'ready':
                return True, message
            elif message['status'] == 'launch_error':
                return False, None
            else:
                raise socket.error("Invalid status: %s" % message['status'])
        except (socket.error, ValueError) as e:
            util.sentry_exc(e)
            return False, None

    def done(self, exitcode=None):
        self.send({"exitcode": exitcode or 0})

    def send(self, data):
        if not self.connection:
            self.connect()
        data = json.dumps(data).encode('utf8') + b'\0'
        self.connection.sendall(data)


class Client(object):
    """Socket client used in the wandb process"""

    def __init__(self, port=None):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.settimeout(1.0)
        self.port = port
        if self.port:
            try:
                self.socket.connect(('localhost', self.port))
            except socket.gaierror:
                self.socket.connect(('127.0.0.1', self.port))
            self.connected = True
        else:
            self.connected = False

    def send(self, data):
        data = json.dumps(data).encode('utf8') + b'\0'
        if self.connected:
            self.socket.sendall(data)

    def recv(self, limit):
        if self.connected:
            return bytearray(self.socket.recv(limit))
        else:
            return bytearray()

    def ready(self):
        self.send({'status': 'ready'})

    def launch_error(self):
        self.send({'status': 'launch_error'})
