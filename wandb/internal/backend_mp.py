import multiprocessing
import threading
import json
import atexit
import queue


from wandb.internal import wandb_internal_pb2
from wandb.internal import datastore

from wandb.apis import internal
from wandb.apis import file_stream

api = internal.Api()
settings=dict(entity="jeff", project="uncategorized")

def wandb_write(q, stopped):
    ds = datastore.DataStore()
    ds.open("out.dat")
    while not stopped.isSet():
        try:
            i = q.get(timeout=1)
        except queue.Empty:
            continue
        ds.write(i)
        #print("write", i)
    ds.close()


def wandb_send(q, stopped):
    while not stopped.isSet():
        try:
            i = q.get(timeout=1)
        except queue.Empty:
            continue
        #print("send", i)

        t = i.WhichOneof("data")
        if t is None:
            continue
        elif t == "run":
            run = i.run
            config = json.loads(run.config_json)
            r = api.upsert_run(name=run.run_id, config=config, **settings)
            #fs = file_stream.FileStreamApi(api, run.run_id, settings=settings)
            #fs.start()
            #self._fs['rfs'] = fs
            #self._fs['run_id'] = run.run_id
        elif t == "log":
            continue
        else:
            print("what", t)


def wandb_internal(notify_queue, process_queue, child_pipe):
    #fd = multiprocessing.reduction.recv_handle(child_pipe)
    #if msvcrt:
    #    fd = msvcrt.open_osfhandle(fd, os.O_WRONLY)
    #os.write(fd, "this is a test".encode())
    #os.close(fd)

    stopped = threading.Event()
   
    write_queue = queue.Queue()
    write_thread = threading.Thread(name="wandb_write", target=wandb_write, args=(write_queue, stopped))
    send_queue = queue.Queue()
    send_thread = threading.Thread(name="wandb_send", target=wandb_send, args=(send_queue, stopped))

    write_thread.start()
    send_thread.start()
    
    while True:
        i = notify_queue.get()
        #print("got", i)
        if i == Backend.NOTIFY_PROCESS:
            rec = process_queue.get()
            send_queue.put(rec)
            write_queue.put(rec)
        elif i == Backend.NOTIFY_SHUTDOWN:
            # make sure queue is empty?
            stopped.set()
            break
        else:
            print("unknown", i)

    write_thread.join()
    send_thread.join()


class Backend(object):
    NOTIFY_PROCESS = 1
    NOTIFY_SHUTDOWN = 2

    def __init__(self, mode=None):
        self.wandb_process = None
        self.fd_pipe_parent = None
        self.process_queue = None
        self.async_queue = None
        self.fd_request_queue = None
        self.fd_response_queue = None
        self.request_queue = None
        self.response_queue = None
        self.notify_queue = None  # notify activity on ...

        self._done = False

    def ensure_launched(self):
        """Launch backend worker if not running."""
        fd_pipe_child, fd_pipe_parent = multiprocessing.Pipe()
        process_queue = multiprocessing.Queue()
        async_queue = multiprocessing.Queue()
        fd_request_queue = multiprocessing.Queue()
        fd_response_queue = multiprocessing.Queue()
        request_queue = multiprocessing.Queue()
        response_queue = multiprocessing.Queue()
        notify_queue = multiprocessing.Queue()

        wandb_process = multiprocessing.Process(target=wandb_internal,
                args=(
                    notify_queue,
                    process_queue,
                    fd_pipe_child,
                    ))
        wandb_process.name = "wandb_internal"
        wandb_process.start()

        self.wandb_process = wandb_process
        self.fd_pipe_parent = fd_pipe_parent
        self.process_queue = process_queue
        self.async_queue = async_queue
        self.fd_request_queue = fd_request_queue
        self.fd_response_queue = fd_response_queue
        self.request_queue = request_queue
        self.response_queue = response_queue
        self.notify_queue = notify_queue

        atexit.register(lambda: self._atexit_cleanup())

    def server_connect(self):
        """Connect to server."""
        pass

    def server_status(self):
        """Report server status."""
        pass

    def join(self):
        self._atexit_cleanup()

    def log(self, data):
        json_data = json.dumps(data)
        l = wandb_internal_pb2.LogData(json=json_data)
        rec = wandb_internal_pb2.Record()
        rec.log.CopyFrom(l)
        self.process_queue.put(rec)
        self.notify_queue.put(self.NOTIFY_PROCESS)

    def run_update(self, run_dict):
        run = wandb_internal_pb2.Run()
        run.run_id = run_dict['run_id']
        run.config_json = json.dumps(run_dict.get('config', {}))
        rec = wandb_internal_pb2.Record()
        rec.run.CopyFrom(run)
        self.process_queue.put(rec)
        self.notify_queue.put(self.NOTIFY_PROCESS)

    def _atexit_cleanup(self):
        # TODO: make _done atomic
        if self._done:
            return
        self._done = True

        self.notify_queue.put(self.NOTIFY_SHUTDOWN)
        # TODO: make sure this is last in the queue?  lock?
        self.notify_queue.close()
        self.wandb_process.join()
