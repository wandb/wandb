import json
import sys

import wandb
import multiprocessing
from multiprocessing import Process
from _pytest.config import get_config  # type: ignore
from pytest_mock import _get_mock_module  # type: ignore
from wandb.proto import wandb_internal_pb2  # type: ignore

# TODO: consolidate dynamic imports
PY3 = sys.version_info.major == 3 and sys.version_info.minor >= 6
if PY3:
    from wandb.sdk.interface import interface
else:
    from wandb.sdk_py27.interface import interface


class ProcessMock(Process):
    def __init__(self, *args, **kwargs):
        self.name = "wandb_internal"
        self._is_alive = True

    def is_alive(self):
        return self._is_alive

    def start(self):
        pass

    def run(self):
        pass

    def join(self, *args):
        self.is_alive = False

    def kill(self):
        self.is_alive = False

    def terminate(self):
        self.is_alive = False

    def close(self):
        self.is_alive = False


class BackendMock(object):
    def __init__(self, mode=None, settings=None, log_level=None):
        self.calls = {}
        self._run = None
        self._done = True
        self._multiprocessing = multiprocessing
        self.record_q = self._multiprocessing.Queue()
        self.result_q = self._multiprocessing.Queue()
        self.interface = None
        self.last_queued = None
        self.history = []
        self.summary = {}
        self.config = {}
        self.files = {}
        self.mocker = _get_mock_module(get_config())
        self._internal_pid = None
        self._settings = settings
        self._log_level = log_level

    def _hack_set_run(self, run):
        self._run = run
        self.interface._hack_set_run(run)

    def _communicate(self, rec, timeout=5, local=False):
        resp = wandb_internal_pb2.Result()
        record_type = rec.WhichOneof("record_type")
        if record_type == "request":
            req = rec.request
            req_type = req.WhichOneof("request_type")
            if req_type == "poll_exit":
                resp.response.poll_exit_response.done = True
        return resp

    def _proto_to_dict(self, obj_list):
        d = dict()
        for item in obj_list:
            d[item.key] = json.loads(item.value_json)
        return d

    def _publish(self, rec):
        if len(rec.history.item) > 0:
            hist = self._proto_to_dict(rec.history.item)
            # handle case where step is not passed in items
            if rec.history.HasField("step"):
                hist["_step"] = rec.history.step.num
            self.history.append(hist)
        if len(rec.summary.update) > 0:
            self.summary.update(self._proto_to_dict(rec.summary.update))
        if len(rec.files.files) > 0:
            for k in rec.files.files:
                fpath = k.path
                fpolicy = k.policy
                # TODO(jhr): fix paths with directories
                self.files[fpath] = fpolicy
        if rec.run:
            pass

        self.last_queued = rec
        self.interface._orig_publish(rec)

    def ensure_launched(self, *args, **kwargs):
        print("Fake Backend Launched")
        wandb_process = ProcessMock()
        self.interface = interface.BackendSender(
            process=wandb_process, record_q=self.record_q, result_q=self.result_q,
        )
        self.interface._communicate = self._communicate
        self.interface._orig_publish = self.interface._publish
        self.interface._publish = self._publish

    def server_connect(self):
        pass

    def server_status(self):
        pass

    def cleanup(self):
        #  self.notify_queue.put(constants.NOTIFY_SHUTDOWN) # TODO: shut it down
        self.interface.join()
        self.record_q.close()
        self.result_q.close()
