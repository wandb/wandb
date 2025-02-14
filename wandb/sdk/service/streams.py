"""streams: class that manages internal threads for each run.

StreamThread: Thread that runs internal.wandb_internal()
StreamRecord: All the external state for the internal thread (queues, etc)
StreamAction: Lightweight record for stream ops for thread safety
StreamMux: Container for dictionary of stream threads per runid
"""

from __future__ import annotations

import asyncio
import functools
import queue
import threading
import time
from threading import Event
from typing import Any, Callable, NoReturn

import psutil

import wandb
import wandb.util
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.interface.interface_relay import InterfaceRelay
from wandb.sdk.interface.router_relay import MessageRelayRouter
from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.sdk.lib import asyncio_compat, progress
from wandb.sdk.lib import printer as printerlib
from wandb.sdk.mailbox import Mailbox, MailboxHandle, wait_all_with_progress
from wandb.sdk.wandb_run import Run


class StreamThread(threading.Thread):
    """Class to running internal process as a thread."""

    def __init__(self, target: Callable, kwargs: dict[str, Any]) -> None:
        threading.Thread.__init__(self)
        self.name = "StreamThr"
        self._target = target
        self._kwargs = kwargs
        self.daemon = True

    def run(self) -> None:
        # TODO: catch exceptions and report errors to scheduler
        self._target(**self._kwargs)


class StreamRecord:
    _record_q: queue.Queue[pb.Record]
    _result_q: queue.Queue[pb.Result]
    _relay_q: queue.Queue[pb.Result]
    _iface: InterfaceRelay
    _thread: StreamThread
    _settings: SettingsStatic
    _started: bool

    def __init__(self, settings: SettingsStatic) -> None:
        self._started = False
        self._mailbox = Mailbox()
        self._record_q = queue.Queue()
        self._result_q = queue.Queue()
        self._relay_q = queue.Queue()
        self._router = MessageRelayRouter(
            request_queue=self._record_q,
            response_queue=self._result_q,
            relay_queue=self._relay_q,
            mailbox=self._mailbox,
        )
        self._iface = InterfaceRelay(
            record_q=self._record_q,
            result_q=self._result_q,
            relay_q=self._relay_q,
            mailbox=self._mailbox,
        )
        self._settings = settings

    def start_thread(self, thread: StreamThread) -> None:
        self._thread = thread
        thread.start()
        self._wait_thread_active()

    def _wait_thread_active(self) -> None:
        self._iface.deliver_status().wait_or(timeout=None)

    def join(self) -> None:
        self._iface.join()
        self._router.join()
        if self._thread:
            self._thread.join()

    def drop(self) -> None:
        self._iface._drop = True

    @property
    def interface(self) -> InterfaceRelay:
        return self._iface

    def mark_started(self) -> None:
        self._started = True

    def update(self, settings: SettingsStatic) -> None:
        # Note: Currently just overriding the _settings attribute
        # once we use Settings Class we might want to properly update it
        self._settings = settings


class StreamAction:
    _action: str
    _stream_id: str
    _processed: Event
    _data: Any

    def __init__(self, action: str, stream_id: str, data: Any | None = None):
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
    _streams: dict[str, StreamRecord]
    _port: int | None
    _pid: int | None
    _action_q: queue.Queue[StreamAction]
    _stopped: Event
    _pid_checked_ts: float | None

    def __init__(self) -> None:
        self._streams_lock = threading.Lock()
        self._streams = dict()
        self._port = None
        self._pid = None
        self._stopped = Event()
        self._action_q = queue.Queue()
        self._pid_checked_ts = None

    def _get_stopped_event(self) -> Event:
        # TODO: clean this up, there should be a better way to abstract this
        return self._stopped

    def set_port(self, port: int) -> None:
        self._port = port

    def set_pid(self, pid: int) -> None:
        self._pid = pid

    def add_stream(self, stream_id: str, settings: SettingsStatic) -> None:
        action = StreamAction(action="add", stream_id=stream_id, data=settings)
        self._action_q.put(action)
        action.wait_handled()

    def start_stream(self, stream_id: str) -> None:
        action = StreamAction(action="start", stream_id=stream_id)
        self._action_q.put(action)
        action.wait_handled()

    def update_stream(self, stream_id: str, settings: SettingsStatic) -> None:
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

    def stream_names(self) -> list[str]:
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
        settings = action._data
        thread = StreamThread(
            target=wandb.wandb_sdk.internal.internal.wandb_internal,  # type: ignore
            kwargs=dict(
                settings=settings,
                record_q=stream._record_q,
                result_q=stream._result_q,
                port=self._port,
                user_pid=self._pid,
            ),
        )
        stream.start_thread(thread)
        with self._streams_lock:
            self._streams[action._stream_id] = stream

    def _process_start(self, action: StreamAction) -> None:
        with self._streams_lock:
            self._streams[action._stream_id].mark_started()

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
            if action._stream_id in self._streams:
                stream = self._streams.pop(action._stream_id)
                stream.drop()
                stream.join()

    async def _finish_all_progress(
        self,
        progress_printer: progress.ProgressPrinter,
        streams_to_watch: dict[str, StreamRecord],
    ) -> None:
        """Poll the streams and display statistics about them.

        This never returns and must be cancelled.

        Args:
            progress_printer: Printer to use for displaying finish progress.
            streams_to_watch: Streams to poll for finish progress.
        """
        results: dict[str, pb.Result | None] = {}

        async def loop_poll_stream(
            stream_id: str,
            stream: StreamRecord,
        ) -> NoReturn:
            while True:
                start_time = time.monotonic()

                handle = stream.interface.deliver_poll_exit()
                results[stream_id] = await handle.wait_async(timeout=None)

                elapsed_time = time.monotonic() - start_time
                if elapsed_time < 1:
                    await asyncio.sleep(1 - elapsed_time)

        async def loop_update_printer() -> NoReturn:
            while True:
                poll_exit_responses: list[pb.PollExitResponse] = []
                for result in results.values():
                    if not result or not result.response:
                        continue
                    if poll_exit_response := result.response.poll_exit_response:
                        poll_exit_responses.append(poll_exit_response)

                progress_printer.update(poll_exit_responses)
                await asyncio.sleep(1)

        async with asyncio_compat.open_task_group() as task_group:
            for stream_id, stream in streams_to_watch.items():
                task_group.start_soon(loop_poll_stream(stream_id, stream))
            task_group.start_soon(loop_update_printer())

    def _finish_all(self, streams: dict[str, StreamRecord], exit_code: int) -> None:
        if not streams:
            return

        printer = printerlib.new_printer()

        # fixme: for now we have a single printer for all streams,
        # and jupyter is disabled if at least single stream's setting set `_jupyter` to false
        exit_handles: list[MailboxHandle[pb.Result]] = []

        # only finish started streams, non started streams failed early
        started_streams: dict[str, StreamRecord] = {}
        not_started_streams: dict[str, StreamRecord] = {}
        for stream_id, stream in streams.items():
            d = started_streams if stream._started else not_started_streams
            d[stream_id] = stream

        for stream in started_streams.values():
            handle = stream.interface.deliver_exit(exit_code)
            exit_handles.append(handle)

        with progress.progress_printer(
            printer,
            default_text="Finishing up...",
        ) as progress_printer:
            # todo: should we wait for the max timeout (?) of all exit handles or just wait forever?
            # timeout = max(stream._settings._exit_timeout for stream in streams.values())
            wait_all_with_progress(
                exit_handles,
                timeout=None,
                progress_after=1,
                display_progress=functools.partial(
                    self._finish_all_progress,
                    progress_printer,
                    started_streams,
                ),
            )

        # These could be done in parallel in the future
        for _sid, stream in started_streams.items():
            # dispatch all our final requests
            poll_exit_handle = stream.interface.deliver_poll_exit()
            final_summary_handle = stream.interface.deliver_get_summary()
            sampled_history_handle = stream.interface.deliver_request_sampled_history()
            internal_messages_handle = stream.interface.deliver_internal_messages()

            result = internal_messages_handle.wait_or(timeout=None)
            internal_messages_response = result.response.internal_messages_response

            result = poll_exit_handle.wait_or(timeout=None)
            poll_exit_response = result.response.poll_exit_response

            result = sampled_history_handle.wait_or(timeout=None)
            sampled_history = result.response.sampled_history_response

            result = final_summary_handle.wait_or(timeout=None)
            final_summary = result.response.get_summary_response

            Run._footer(
                sampled_history=sampled_history,
                final_summary=final_summary,
                poll_exit_response=poll_exit_response,
                internal_messages_response=internal_messages_response,
                settings=stream._settings,  # type: ignore
                printer=printer,
            )
            stream.join()

        # not started streams need to be cleaned up
        for stream in not_started_streams.values():
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
        if action._action == "start":
            self._process_start(action)
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
                # parent process is gone, let other threads know we need to shut down
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
