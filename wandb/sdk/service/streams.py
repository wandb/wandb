"""streams: class that manages internal threads for each run.

StreamThread: Thread that runs internal.wandb_internal()
StreamRecord: All the external state for the internal thread (queues, etc)
StreamAction: Lightweight record for stream ops for thread safety with grpc
StreamMux: Container for dictionary of stream threads per runid
"""
import logging
import multiprocessing
import queue
import threading
from threading import Event
import time
from typing import Any, Callable, Dict, List, Optional

import psutil
import wandb
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.sdk.lib.printer import get_printer
from wandb.sdk.wandb_run import Run

# from wandb.sdk.wandb_settings import Settings

from ..interface.interface_relay import InterfaceRelay


class StreamThread(threading.Thread):
    """Class to running internal process as a thread."""

    def __init__(self, target: Callable, kwargs: Dict[str, Any]) -> None:
        threading.Thread.__init__(self)
        self.name = "StreamThr"
        self._target = target
        self._kwargs = kwargs
        self.daemon = True

    def run(self) -> None:
        # TODO: catch exceptions and report errors to scheduler
        self._target(**self._kwargs)


class StreamRecord:
    _record_q: "multiprocessing.Queue[pb.Record]"
    _result_q: "multiprocessing.Queue[pb.Result]"
    _relay_q: "multiprocessing.Queue[pb.Result]"
    _iface: InterfaceRelay
    _thread: StreamThread
    _settings: SettingsStatic  # TODO(settings) replace SettingsStatic with Setting

    def __init__(self, settings: Dict[str, Any]) -> None:
        self._record_q = multiprocessing.Queue()
        self._result_q = multiprocessing.Queue()
        self._relay_q = multiprocessing.Queue()
        process = multiprocessing.current_process()
        self._iface = InterfaceRelay(
            record_q=self._record_q,
            result_q=self._result_q,
            relay_q=self._relay_q,
            process=process,
            process_check=False,
        )
        self._settings = SettingsStatic(settings)

    def start_thread(self, thread: StreamThread) -> None:
        self._thread = thread
        thread.start()
        self._wait_thread_active()

    def _wait_thread_active(self) -> None:
        result = self._iface.communicate_status()
        # TODO: using the default communicate timeout, is that enough? retries?
        assert result

    def join(self) -> None:
        self._iface.join()
        self._record_q.close()
        self._result_q.close()
        self._relay_q.close()
        if self._thread:
            self._thread.join()

    def drop(self) -> None:
        self._iface._drop = True

    @property
    def interface(self) -> InterfaceRelay:
        return self._iface

    def update(self, settings: Dict[str, Any]) -> None:
        # Note: Currently just overriding the _settings attribute
        # once we use Settings Class we might want to properly update it
        self._settings = SettingsStatic(settings)


class StreamAction:
    _action: str
    _stream_id: str
    _processed: Event
    _data: Any

    def __init__(self, action: str, stream_id: str, data: Any = None):
        self._action = action
        self._stream_id = stream_id
        self._data = data
        self._processed = Event()

    def __repr__(self) -> str:
        return f"StreamAction({self._action},{self._stream_id})"

    def wait_handled(self) -> None:
        self._processed.wait()

    def set_handled(self) -> None:
        self._processed.set()

    @property
    def stream_id(self) -> str:
        return self._stream_id


class StreamMux:
    _streams_lock: threading.Lock
    _streams: Dict[str, StreamRecord]
    _port: Optional[int]
    _pid: Optional[int]
    _action_q: "queue.Queue[StreamAction]"
    _stopped: Event
    _pid_checked_ts: Optional[float]

    def __init__(self) -> None:
        self._streams_lock = threading.Lock()
        self._streams = dict()
        self._port = None
        self._pid = None
        self._stopped = Event()
        self._action_q = queue.Queue()
        self._pid_checked_ts = None

    def _get_stopped_event(self) -> "Event":
        # TODO: clean this up, there should be a better way to abstract this
        return self._stopped

    def set_port(self, port: int) -> None:
        self._port = port

    def set_pid(self, pid: int) -> None:
        self._pid = pid

    def add_stream(self, stream_id: str, settings: Dict[str, Any]) -> None:
        action = StreamAction(action="add", stream_id=stream_id, data=settings)
        self._action_q.put(action)
        action.wait_handled()

    def update_stream(self, stream_id: str, settings: Dict[str, Any]) -> None:
        action = StreamAction(action="update", stream_id=stream_id, data=settings)
        self._action_q.put(action)
        action.wait_handled()

    def del_stream(self, stream_id: str) -> None:
        action = StreamAction(action="del", stream_id=stream_id)
        self._action_q.put(action)
        action.wait_handled()

    def drop_stream(self, stream_id: str) -> None:
        action = StreamAction(action="drop", stream_id=stream_id)
        self._action_q.put(action)
        action.wait_handled()

    def teardown(self, exit_code: int) -> None:
        action = StreamAction(action="teardown", stream_id="na", data=exit_code)
        self._action_q.put(action)
        action.wait_handled()

    def stream_names(self) -> List[str]:
        with self._streams_lock:
            names = list(self._streams.keys())
            return names

    def has_stream(self, stream_id: str) -> bool:
        with self._streams_lock:
            return stream_id in self._streams

    def get_stream(self, stream_id: str) -> StreamRecord:
        with self._streams_lock:
            stream = self._streams[stream_id]
            return stream

    def _process_add(self, action: StreamAction) -> None:
        stream = StreamRecord(action._data)
        # run_id = action.stream_id  # will want to fix if a streamid != runid
        settings_dict = action._data
        settings_dict[
            "_log_level"
        ] = (
            logging.DEBUG
        )  # Note: not including this in the stream's settings to try and keep only Settings arguments
        thread = StreamThread(
            target=wandb.wandb_sdk.internal.internal.wandb_internal,
            kwargs=dict(
                settings=settings_dict,
                record_q=stream._record_q,
                result_q=stream._result_q,
                port=self._port,
                user_pid=self._pid,
            ),
        )
        stream.start_thread(thread)
        with self._streams_lock:
            self._streams[action._stream_id] = stream

    def _process_update(self, action: StreamAction) -> None:
        with self._streams_lock:
            self._streams[action._stream_id].update(action._data)

    def _process_del(self, action: StreamAction) -> None:
        with self._streams_lock:
            stream = self._streams.pop(action._stream_id)
            stream.join()
        # TODO: we assume stream has already been shutdown.  should we verify?

    def _process_drop(self, action: StreamAction) -> None:
        with self._streams_lock:
            stream = self._streams.pop(action._stream_id)
            stream.drop()
            stream.join()

    def _finish_all(self, streams: Dict[str, StreamRecord], exit_code: int) -> None:
        if not streams:
            return

        # TODO(settings) remove type ignore once SettingsStatic and Settings unified
        print("")
        printer = get_printer(
            all(stream._settings._jupyter for stream in streams.values())
        )
        # fixme: for now we have a single printer for all streams,
        # and jupyter is disabled if at least single stream's setting set `_jupyter` to false
        for stream in streams.values():
            stream.interface.publish_exit(exit_code)
            Run._footer_exit_status_info(
                exit_code, settings=stream._settings, printer=printer  # type: ignore
            )

        streams_to_join, poll_exit_responses = {}, {}
        while streams:
            # Note that we materialize the generator so we can modify the underlying list
            for sid, stream in list(streams.items()):
                poll_exit_response = stream.interface.communicate_poll_exit()
                poll_exit_responses[sid] = poll_exit_response
                if poll_exit_response and poll_exit_response.done:
                    streams.pop(sid)
                    streams_to_join[sid] = stream
            Run._footer_file_pusher_status_info(poll_exit_responses, printer=printer)
            time.sleep(0.1)

        # TODO: this would be nice to do in parallel
        for sid, stream in streams_to_join.items():
            history = (
                stream.interface.communicate_sampled_history()
                if stream.interface
                else None
            )
            summary = (
                stream.interface.communicate_get_summary() if stream.interface else None
            )
            Run._footer(
                history,
                summary,
                poll_exit_responses[sid],
                settings=stream._settings,  # type: ignore
                printer=printer,
            )
            stream.join()

    def _process_teardown(self, action: StreamAction) -> None:
        exit_code: int = action._data
        with self._streams_lock:
            # TODO: mark streams to prevent new modifications?
            streams_copy = self._streams.copy()
        self._finish_all(streams_copy, exit_code)
        with self._streams_lock:
            self._streams = dict()
        self._stopped.set()

    def _process_action(self, action: StreamAction) -> None:
        if action._action == "add":
            self._process_add(action)
            return
        if action._action == "update":
            self._process_update(action)
            return
        if action._action == "del":
            self._process_del(action)
            return
        if action._action == "drop":
            self._process_drop(action)
            return
        if action._action == "teardown":
            self._process_teardown(action)
            return
        raise AssertionError(f"Unsupported action: {action._action}")

    def _check_orphaned(self) -> bool:
        if not self._pid:
            return False
        time_now = time.time()
        # if we have checked already and it was less than 2 seconds ago
        if self._pid_checked_ts and time_now < self._pid_checked_ts + 2:
            return False
        self._pid_checked_ts = time_now
        return not psutil.pid_exists(self._pid)

    def _loop(self) -> None:
        while not self._stopped.is_set():
            if self._check_orphaned():
                # parent process is gone, let other threads know we need to shutdown
                self._stopped.set()
            try:
                action = self._action_q.get(timeout=1)
            except queue.Empty:
                continue
            self._process_action(action)
            action.set_handled()
            self._action_q.task_done()
        self._action_q.join()

    def loop(self) -> None:
        try:
            self._loop()
        except Exception as e:
            raise e

    def cleanup(self) -> None:
        pass
