import wandb

import json
import multiprocessing as mp
import os
import psutil
import queue
import socketserver
import threading
import time
import uuid
from six.moves import cPickle as pickle



def _get_free_port():
    with socketserver.TCPServer(("localhost", 0), None) as s:
        return s.server_address[1]

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
                    except  Exception as e:
                        try:
                            conn.send(e)
                        except Exception:
                            conn.send(Exception())
            else:
                    try:
                        conn.send(msg)
                    except  Exception as e:
                        try:
                            conn.send(e)
                        except Exception:
                            conn.send(Exception())

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

    def send(self, req):
        with self._lock:
            self._client.send(req)

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


def start_mp_server(port):
    server = Server(('localhost', port), responder=_response)


_cache = {}
def _ret_obj(obj):
    if callable(obj):
        key = str(uuid.uuid1())
        _cache[key] = obj
        return {"type": "reference", "key": key}
    else:
        try:
            pickle.dumps(obj)
            return {"type": "value", "value": obj}
        except Exception:
            key = str(uuid.uuid1())
            _cache[key] = obj
            return {"type": "reference", "key": key}


def _response(req):
    try:
        req_type = req["type"]
        if req_type == "getattr":
            obj = eval(req["code"])
            attr = req["attr"]
            ret = getattr(obj, attr)
            return _ret_obj(ret)
        elif req_type == "setattr":
            obj = eval(req["code"])
            attr = req["attr"]
            val = req["val"]
            setattr(obj, attr, val)
        elif req_type == "getitem":
            obj = eval(req["code"])
            attr = req["attr"]
            ret = obj[attr]
            return _ret_obj(ret)
        elif req_type == "setitem":
            obj = eval(req["code"])
            attr = req["attr"]
            val = req["val"]
            obj[attr] = val
        elif req_type == "call":
            f = req["func"]
            f = eval(f)
            args = req.get("args", ())
            kwargs = req.get("kwargs", {})
            obj = f(*args, **kwargs)
            return _ret_obj(obj)
        elif req_type == "str":
            obj = eval(req["code"])
            s = str(obj)
            return _ret_obj(s)
    except Exception as e:
        return e

class Proxy(object):
    def __init__(self, base, port=None):
        object.__setattr__(self, 'base', base)
        if port is not None:
            object.__setattr__(self, '_client', SyncClient(('localhost', port)))

    def _ret_resp(self, resp):
        if isinstance(resp, Exception):
            raise resp
        typ = resp["type"]
        if typ == "error":
            raise resp["error"]
        elif typ == "value":
            return resp["value"]
        elif typ == "reference":
            p = Proxy("_cache['%s']" % resp["key"])
            object.__setattr__(p, '_client', object.__getattribute__(self, '_client'))
            return p

    def __getattr__(self, attr):
        client = object.__getattribute__(self, '_client')
        ret = object.__getattribute__(self, '_ret_resp')
        base = object.__getattribute__(self, 'base')
        req = {"type": "getattr", "code": base, "attr": attr}
        resp = client.get(req)
        return ret(resp)

    def __getitem__(self, attr):
        client = object.__getattribute__(self, '_client')
        ret = object.__getattribute__(self, '_ret_resp')
        base = object.__getattribute__(self, 'base')
        req = {"type": "getitem", "code": base, "attr": attr}
        resp = client.get(req)
        return ret(resp)

    def __call__(self, *args, **kwargs):
        client = object.__getattribute__(self, '_client')
        ret = object.__getattribute__(self, '_ret_resp')
        base = object.__getattribute__(self, 'base')
        req = {"type": "call", "func": base, "args": args, "kwargs": kwargs}
        resp = client.get(req)
        return ret(resp)

    def __setattr__(self, attr, val):
        client = object.__getattribute__(self, '_client')
        base = object.__getattribute__(self, 'base')
        req = {"type": "setattr", "code": base, "attr": attr, "val": val}
        client.send(req)

    def __setitem__(self, attr, val):
        client = object.__getattribute__(self, '_client')
        base = object.__getattribute__(self, 'base')
        req = {"type": "setitem", "code": base, "attr": attr, "val": val}
        client.send(req)

    def __str__(self):
        client = object.__getattribute__(self, '_client')
        base = object.__getattribute__(self, 'base')
        ret = object.__getattribute__(self, '_ret_resp')
        req = {"type": "str", "code": base}
        s = ret(client.get(req))
        assert isinstance(s, str)
        return "<Proxy for %s>" % s


def _write_process_config(kwargs, port, wandb_dir=None):
    required_keys = [
        "monitor_gym",
        "tensorboard",
        "sync_tensorboard",
        "magic"
    ]
    kwargs2 = {k: kwargs.get(k) for k in required_keys}

    config = {
        "id": os.getpid(),
        "port": port,
        "kwargs": kwargs2
    }
    if wandb_dir is None:
        wandb_dir = wandb.old.core.wandb_dir()
    if not os.path.isdir(wandb_dir):
        os.mkdir(wandb_dir)
    with open(os.path.join(wandb_dir, "proc_%s.json" % os.getpid()), 'w') as f:
        json.dump(config, f)


def _get_parent_process_config(wandb_dir=None):
    ppid = psutil.Process(os.getpid()).ppid()
    if wandb_dir is None:
        wandb_dir = wandb.old.core.wandb_dir()
    parent_config_file = os.path.join(wandb_dir, "proc_%s.json" % ppid)
    if not os.path.isfile(parent_config_file):
        return None
    with open(parent_config_file, 'r') as f:
        return json.load(f)

