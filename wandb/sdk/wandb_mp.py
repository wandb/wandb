import wandb

import multiprocessing as mp
import queue
import socketserver
import threading
import time
import uuid


class Server(object):
    def __init__(self, address, handler=None, responder=None):
        self.address = address
        self.handler = handler
        self.responder = responder
        self._listener = mp.connection.Listener(address)
        self._connections = []
        self._receiver_threads = []
        self._stop = threading.Event()
        self._connect_thread = threading.Thread(target=self._connect_loop)
        self._connect_thread.daemon = True
        self._connect_thread.start()
        self._queue = queue.Queue()
        self._sender_thread = threading.Thread(target=self._sender_loop)
        self._sender_thread.daemon = True
        self._sender_thread.start()

    def _sender_loop(self):
        while not self._stop.is_set():
            conn, msg = self._queue.get()
            if conn is None:
                for conn in self._connections:
                    try:
                        conn.send(msg)
                    except  Exception:
                        pass  # TODO(frz)
            else:
                try:
                    conn.send(msg)
                except  Exception:
                    pass  # TODO(frz) 

    def _receiver_loop(self, connection):
        while not self._stop.is_set():
            try:
                msg = connection.recv()
                if self.handler:
                    self.handler(msg)
                if self.responder:
                    self._queue.put((connection, self.responder(msg)))
            except Exception:
                pass  # TODO(frz)

    def _connect_loop(self):
        while not self._stop.is_set():
            try:
                conn = self._listener.accept()
                self._connections.append(conn)
                t = threading.Thread(target=self._receiver_loop, args=(conn,))
                t.daemon = True
                t.start()
                self._receiver_threads.append(t)
            except Exception:
                pass  # happens during shutdown

    def send(self, msg):
        self._queue.put((None, msg))

    def stop(self):
        self._stop.set()
        self._connect_thread.join(timeout=5)
        self._sender_thread.join(timeout=5)
        for conn in self._connections:
            conn.close()
        self._listener.close()
        # TODO(frz): kill receiver threads


class SyncClient(object):
    def __init__(self, address):
        self.address = address
        self._client = None
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._lock = threading.Lock()
        self._connect_thread = threading.Thread(target=self._connect)
        self._connect_thread.daemon = True
        self._connect_thread.start()

    def _connect(self):
        while not self._connected.is_set() and not self._stop.is_set():
            try:
                self._client = mp.connection.Client(self.address)
                self._connected.set()
            except Exception:
                pass

    def get(self, req):
        self._connected.wait()
        with self._lock:
            self._client.send(req)
            return self._client.recv()

    def close(self):
        if not self._connected.is_set():
            self._connect_thread.join(timeout=3)
        self._stop.set()
        with self._lock:
            self._client.close()


class AsyncClient(object):
    def __init__(self, address, handler=None, responder=None):
        self.address = address
        self.handler = handler
        self.responder = responder
        self._client = None
        self._connected = threading.Event()
        self._stop = threading.Event()
        self._receiver_thread = threading.Thread(target=self._receiver_loop)
        self._receiver_thread.daemon = True
        self._connect_thread = threading.Thread(target=self._connect)
        self._connect_thread.daemon = True
        self._connect_thread.start()
        self._receiver_thread.start()
        self._queue = queue.Queue()
        self._sender_thread = threading.Thread(target=self._sender_loop)
        self._sender_thread.daemon = True
        self._sender_thread.start()
        self._requests = set()

    def _connect(self):
        while not self._connected.is_set() and not self._stop.is_set():
            try:
                self._client = mp.connection.Client(self.address)
                self._connected.set()
            except Exception:
                pass

    def _receiver_loop(self):
        self._connected.wait()
        while not self._stop.is_set():
            try:
                msg = self._client.recv()
                if self.handler:
                    self.handler(msg)
                if self.responder:
                    self.send(self.responder(msg))
            except Exception:
                pass  # TODO(frz)

    def _sender_loop(self):
        self._connected.wait()
        while not self._stop.is_set():
            try:
                self._client.send(self._queue.get())
            except Exception:
                pass

    def send(self, msg):
        self._queue.put(msg)

    def stop(self):
        if not self._connected:
            pass  # TODO(frz) kill connect thread
        self._stop.set()
        self._connect_thread.join(timeout=5)
        # TODO(frz): kill receiver thread
        self._sender_thread.join(timeout=5)
        self._client.close()

    def get(self, request):
        pass

def _get_port():
    with socketserver.TCPServer(("localhost", 0), None) as s:
        free_port = s.server_address[1]

def start_mp_server():
    server = Server(('localhost', 6000), responder=_response)


def _response(req):
    req_type = req["type"]
    if req_type == "eval":
        s = req["code"]
        assert s.startswith("wandb.")
        try:
            obj = eval(s)
        except Exception as e:
            return {"type":"error", "error": e}
        if callable(obj):
            key = str(uuid.uuid1())
            _cache[key] = obj
            return {"type": "reference", "key": key}
        else:
            try:
                return {"type": "value", "value": obj}
            except TypeError:
                key = str(uuid.uuid1())
                _cache[key] = obj
                return {"type": "reference", "key": key}
    elif req_type == "call":
        f = req["func"]
        assert f.startswith("wandb.")
        f = eval(f)
        args = req.get("args", ())
        kwargs = req.get("kwargs", {})
        try:
            obj = f(*args, **kwargs)
        except Exception as e:
            return {"type":"error", "error": e}
        if callable(obj):
            key = str(uuid.uuid1())
            _cache[key] = obj
            return {"type": "reference", "key": key}
        else:
            try:
                return {"type": "value", "value": obj}
            except TypeError:
                key = str(uuid.uuid1())
                _cache[key] = obj
                return {"type": "reference", "key": key}


class Proxy(object):
    def __init__(self, base=''):
        self.base = base
        self._client = SyncClient(('localhost', 6000))

    def __getattr__(self, attr):
        s = self.base + '.' + attr
        req = {"type": "eval", "code": s}
        resp = self._client.get(req)
        typ = resp["type"]
        if typ == "error":
            raise resp["error"]
        elif typ == "value":
            return resp["value"]
        elif typ == "reference":
            p = Proxy("_cache[%s]" % resp["key"])
            return p

    def __call__(self, *args, **kwargs):
        req = {"type": "call", "func": self.base, "args": args, "kwargs": kwargs}
        resp = self._client.get(req)
        typ = resp["type"]
        if typ == "error":
            raise resp["error"]
        elif typ == "value":
            return resp["value"]
        elif typ == "reference":
            p = Proxy("_cache[%s]" % resp["key"])
            return p
