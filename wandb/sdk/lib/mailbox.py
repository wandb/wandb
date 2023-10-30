"""mailbox."""

import secrets
import string
import threading
import time
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Tuple

from wandb.errors import Error
from wandb.proto import wandb_internal_pb2 as pb

if TYPE_CHECKING:
    from wandb.sdk.interface.interface_shared import InterfaceShared


def _generate_address(length: int = 12) -> str:
    address = "".join(
        secrets.choice(string.ascii_lowercase + string.digits) for i in range(length)
    )
    return address


class MailboxError(Error):
    """Generic Mailbox Exception."""

    pass


class ContextCancelledError(MailboxError):
    """Context cancelled Exception."""

    pass


class _MailboxWaitAll:
    _event: threading.Event
    _lock: threading.Lock
    _handles: List["MailboxHandle"]
    _failed_handles: int

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._handles = []
        self._failed_handles = 0

    def notify(self) -> None:
        with self._lock:
            self._event.set()

    def _add_handle(self, handle: "MailboxHandle") -> None:
        handle._slot._set_wait_all(self)
        self._handles.append(handle)

        # set wait_all event if an event has already been set before added to wait_all
        if handle._slot._event.is_set():
            self._event.set()

    @property
    def active_handles(self) -> List["MailboxHandle"]:
        return [h for h in self._handles if not h._is_failed]

    @property
    def active_handles_count(self) -> int:
        return len(self.active_handles)

    @property
    def failed_handles_count(self) -> int:
        return self._failed_handles

    def _mark_handle_failed(self, handle: "MailboxHandle") -> None:
        handle._mark_failed()
        self._failed_handles += 1

    def clear_handles(self) -> None:
        for handle in self._handles:
            handle._slot._clear_wait_all()
        self._handles = []

    def _wait(self, timeout: float) -> bool:
        return self._event.wait(timeout=timeout)

    def _get_and_clear(self, timeout: float) -> List["MailboxHandle"]:
        found: List[MailboxHandle] = []
        if self._wait(timeout=timeout):
            with self._lock:
                remove_handles = []

                # Look through handles for triggered events
                for handle in self._handles:
                    if handle._slot._event.is_set():
                        found.append(handle)
                        remove_handles.append(handle)

                for handle in remove_handles:
                    self._handles.remove(handle)

                self._event.clear()
        return found


class _MailboxSlot:
    _result: Optional[pb.Result]
    _event: threading.Event
    _lock: threading.Lock
    _wait_all: Optional[_MailboxWaitAll]
    _address: str
    _abandoned: bool

    def __init__(self, address: str) -> None:
        self._result = None
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._address = address
        self._wait_all = None
        self._abandoned = False

    def _set_wait_all(self, wait_all: _MailboxWaitAll) -> None:
        assert not self._wait_all, "Only one caller can wait_all for a slot at a time"
        self._wait_all = wait_all

    def _clear_wait_all(self) -> None:
        self._wait_all = None

    def _wait(self, timeout: float) -> bool:
        return self._event.wait(timeout=timeout)

    def _get_and_clear(self, timeout: float) -> Tuple[Optional[pb.Result], bool]:
        found = None
        if self._wait(timeout=timeout):
            with self._lock:
                found = self._result
                self._event.clear()
        abandoned = self._abandoned
        return found, abandoned

    def _deliver(self, result: pb.Result) -> None:
        with self._lock:
            self._result = result
            self._event.set()

        if self._wait_all:
            self._wait_all.notify()

    def _notify_abandon(self) -> None:
        self._abandoned = True
        with self._lock:
            self._event.set()

        if self._wait_all:
            self._wait_all.notify()


class MailboxProbe:
    _result: Optional[pb.Result]
    _handle: Optional["MailboxHandle"]

    def __init__(self) -> None:
        self._handle = None
        self._result = None

    def set_probe_result(self, result: pb.Result) -> None:
        self._result = result

    def get_probe_result(self) -> Optional[pb.Result]:
        return self._result

    def get_mailbox_handle(self) -> Optional["MailboxHandle"]:
        return self._handle

    def set_mailbox_handle(self, handle: "MailboxHandle") -> None:
        self._handle = handle


class MailboxProgress:
    _percent_done: float
    _handle: "MailboxHandle"
    _probe_handles: List[MailboxProbe]
    _stopped: bool

    def __init__(self, _handle: "MailboxHandle") -> None:
        self._handle = _handle
        self._percent_done = 0.0
        self._probe_handles = []
        self._stopped = False

    @property
    def percent_done(self) -> float:
        return self._percent_done

    def set_percent_done(self, percent_done: float) -> None:
        self._percent_done = percent_done

    def add_probe_handle(self, probe_handle: MailboxProbe) -> None:
        self._probe_handles.append(probe_handle)

    def get_probe_handles(self) -> List[MailboxProbe]:
        return self._probe_handles

    def wait_stop(self) -> None:
        self._stopped = True

    @property
    def _is_stopped(self) -> bool:
        return self._stopped


class MailboxProgressAll:
    _progress_handles: List[MailboxProgress]

    def __init__(self) -> None:
        self._progress_handles = []

    def add_progress_handle(self, progress_handle: MailboxProgress) -> None:
        self._progress_handles.append(progress_handle)

    def get_progress_handles(self) -> List[MailboxProgress]:
        # only return progress handles for not failed handles
        return [ph for ph in self._progress_handles if not ph._handle._is_failed]


class MailboxHandle:
    _mailbox: "Mailbox"
    _slot: _MailboxSlot
    _on_probe: Optional[Callable[[MailboxProbe], None]]
    _on_progress: Optional[Callable[[MailboxProgress], None]]
    _interface: Optional["InterfaceShared"]
    _keepalive: bool
    _failed: bool

    def __init__(self, mailbox: "Mailbox", slot: _MailboxSlot) -> None:
        self._mailbox = mailbox
        self._slot = slot
        self._on_probe = None
        self._on_progress = None
        self._interface = None
        self._keepalive = False
        self._failed = False

    def add_probe(self, on_probe: Callable[[MailboxProbe], None]) -> None:
        self._on_probe = on_probe

    def add_progress(self, on_progress: Callable[[MailboxProgress], None]) -> None:
        self._on_progress = on_progress

    def _time(self) -> float:
        return time.monotonic()

    def wait(  # noqa: C901
        self,
        *,
        timeout: float,
        on_probe: Optional[Callable[[MailboxProbe], None]] = None,
        on_progress: Optional[Callable[[MailboxProgress], None]] = None,
        release: bool = True,
        cancel: bool = False,
    ) -> Optional[pb.Result]:
        probe_handle: Optional[MailboxProbe] = None
        progress_handle: Optional[MailboxProgress] = None
        found: Optional[pb.Result] = None
        start_time = self._time()
        percent_done = 0.0
        progress_sent = False
        wait_timeout = 1.0
        if timeout >= 0:
            wait_timeout = min(timeout, wait_timeout)

        on_progress = on_progress or self._on_progress
        if on_progress:
            progress_handle = MailboxProgress(_handle=self)

        on_probe = on_probe or self._on_probe
        if on_probe:
            probe_handle = MailboxProbe()
            if progress_handle:
                progress_handle.add_probe_handle(probe_handle)

        while True:
            if self._keepalive and self._interface:
                if self._interface._transport_keepalive_failed():
                    raise MailboxError("transport failed")

            found, abandoned = self._slot._get_and_clear(timeout=wait_timeout)
            if found:
                # Always update progress to 100% when done
                if on_progress and progress_handle and progress_sent:
                    progress_handle.set_percent_done(100)
                    on_progress(progress_handle)
                break
            if abandoned:
                break
            now = self._time()
            if timeout >= 0:
                if now >= start_time + timeout:
                    # todo: communicate that we timed out
                    break
            if on_probe and probe_handle:
                on_probe(probe_handle)
            if on_progress and progress_handle:
                if timeout > 0:
                    percent_done = min((now - start_time) / timeout, 1.0)
                progress_handle.set_percent_done(percent_done)
                on_progress(progress_handle)
                if progress_handle._is_stopped:
                    break
                progress_sent = True
        if not found and cancel:
            self._cancel()
        if release:
            self._release()
        return found

    def _cancel(self) -> None:
        mailbox_slot = self.address
        if self._interface:
            self._interface.publish_cancel(mailbox_slot)

    def _release(self) -> None:
        self._mailbox._release_slot(self.address)

    def abandon(self) -> None:
        self._slot._notify_abandon()
        self._release()

    @property
    def _is_failed(self) -> bool:
        return self._failed

    def _mark_failed(self) -> None:
        self._failed = True

    @property
    def address(self) -> str:
        return self._slot._address


class Mailbox:
    _slots: Dict[str, _MailboxSlot]
    _keepalive: bool

    def __init__(self) -> None:
        self._slots = {}
        self._keepalive = False

    def enable_keepalive(self) -> None:
        self._keepalive = True

    def wait(
        self,
        handle: MailboxHandle,
        *,
        timeout: float,
        on_progress: Optional[Callable[[MailboxProgress], None]] = None,
        cancel: bool = False,
    ) -> Optional[pb.Result]:
        return handle.wait(timeout=timeout, on_progress=on_progress, cancel=cancel)

    def _time(self) -> float:
        return time.monotonic()

    def wait_all(
        self,
        handles: List[MailboxHandle],
        *,
        timeout: float,
        on_progress_all: Optional[Callable[[MailboxProgressAll], None]] = None,
    ) -> bool:
        progress_all_handle: Optional[MailboxProgressAll] = None

        if on_progress_all:
            progress_all_handle = MailboxProgressAll()

        wait_all = _MailboxWaitAll()
        for handle in handles:
            wait_all._add_handle(handle)
            if progress_all_handle and handle._on_progress:
                progress_handle = MailboxProgress(_handle=handle)
                if handle._on_probe:
                    probe_handle = MailboxProbe()
                    progress_handle.add_probe_handle(probe_handle)
                progress_all_handle.add_progress_handle(progress_handle)

        start_time = self._time()

        while wait_all.active_handles_count > 0:
            # Make sure underlying interfaces are still up
            if self._keepalive:
                for handle in wait_all.active_handles:
                    if not handle._interface:
                        continue
                    if handle._interface._transport_keepalive_failed():
                        wait_all._mark_handle_failed(handle)

                # if there are no valid handles left, either break or raise exception
                if not wait_all.active_handles_count:
                    if wait_all.failed_handles_count:
                        wait_all.clear_handles()
                        raise MailboxError("transport failed")
                    break

            # wait for next event
            wait_all._get_and_clear(timeout=1)

            # TODO: we can do more careful timekeeping and not run probes and progress
            # indications until a full second elapses in the case where we found a wait_all
            # event.  Extra probes should be ok for now.

            if progress_all_handle and on_progress_all:
                # Run all probe handles
                for progress_handle in progress_all_handle.get_progress_handles():
                    for probe_handle in progress_handle.get_probe_handles():
                        if (
                            progress_handle._handle
                            and progress_handle._handle._on_probe
                        ):
                            progress_handle._handle._on_probe(probe_handle)

                on_progress_all(progress_all_handle)

            now = self._time()
            if timeout >= 0 and now >= start_time + timeout:
                break

        return wait_all.active_handles_count == 0

    def deliver(self, result: pb.Result) -> None:
        mailbox = result.control.mailbox_slot
        slot = self._slots.get(mailbox)
        if not slot:
            return
        slot._deliver(result)

    def _allocate_slot(self) -> _MailboxSlot:
        address = _generate_address()
        slot = _MailboxSlot(address=address)
        self._slots[address] = slot
        return slot

    def _release_slot(self, address: str) -> None:
        self._slots.pop(address, None)

    def get_handle(self) -> MailboxHandle:
        slot = self._allocate_slot()
        handle = MailboxHandle(mailbox=self, slot=slot)
        return handle

    def _deliver_record(
        self, record: pb.Record, interface: "InterfaceShared"
    ) -> MailboxHandle:
        handle = self.get_handle()
        handle._interface = interface
        handle._keepalive = self._keepalive
        record.control.mailbox_slot = handle.address
        try:
            interface._publish(record)
        except Exception:
            interface._transport_mark_failed()
            raise
        interface._transport_mark_success()
        return handle
