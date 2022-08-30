"""
mailbox.
"""

import secrets
import string
import threading
import time
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

from wandb import errors
from wandb.proto import wandb_internal_pb2 as pb

if TYPE_CHECKING:
    from wandb.sdk.interface.interface_shared import InterfaceShared


def _generate_address(length: int = 12) -> str:
    address = "".join(
        secrets.choice(string.ascii_lowercase + string.digits) for i in range(length)
    )
    return address


class MailboxError(errors.Error):
    """Generic Mailbox Exception"""

    pass


class _MailboxWaitAll:
    _event: threading.Event
    _lock: threading.Lock
    _handles: List["MailboxHandle"]

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._handles = []

    def notify(self) -> None:
        with self._lock:
            self._event.set()

    def _add_handle(self, handle: "MailboxHandle") -> None:
        handle._slot._set_wait_all(self)
        self._handles.append(handle)

        # set wait_all event if an event has already been set before added to wait_all
        if handle._slot._event.is_set():
            self._event.set()

    def _clear_handles(self) -> None:
        for handle in self._handles:
            handle._slot._clear_wait_all()
        self._handles = []

    def _get_and_clear(self, timeout: float) -> List["MailboxHandle"]:
        found: List["MailboxHandle"] = []
        if self._event.wait(timeout=timeout):
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

    def __init__(self, address: str) -> None:
        self._result = None
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._address = address
        self._wait_all = None

    def _set_wait_all(self, wait_all: _MailboxWaitAll) -> None:
        assert not self._wait_all, "Only one caller can wait_all for a slot at a time"
        self._wait_all = wait_all

    def _clear_wait_all(self) -> None:
        self._wait_all = None

    def _get_and_clear(self, timeout: float) -> Optional[pb.Result]:
        found = None
        if self._event.wait(timeout=timeout):
            with self._lock:
                found = self._result
                self._event.clear()
        return found

    def _deliver(self, result: pb.Result) -> None:
        with self._lock:
            self._result = result
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

    def __init__(self, _handle: "MailboxHandle") -> None:
        self._handle = _handle
        self._percent_done = 0.0
        self._probe_handles = []

    @property
    def percent_done(self) -> float:
        return self._percent_done

    def set_percent_done(self, percent_done: float) -> None:
        self._percent_done = percent_done

    def add_probe_handle(self, probe_handle: MailboxProbe) -> None:
        self._probe_handles.append(probe_handle)

    def get_probe_handles(self) -> List[MailboxProbe]:
        return self._probe_handles


class MailboxProgressAll:
    _progress_handles: List[MailboxProgress]

    def __init__(self) -> None:
        self._progress_handles = []

    def add_progress_handle(self, progress_handle: MailboxProgress) -> None:
        self._progress_handles.append(progress_handle)

    def remove_progress_handle_matching_handle(self, handle: "MailboxHandle") -> None:
        # TODO: make this more efficient in the future so we dont have to walk list
        self._progress_handles = list(
            filter(
                lambda progress_handle: progress_handle._handle != handle,
                self._progress_handles,
            )
        )

    def get_progress_handles(self) -> List[MailboxProgress]:
        return self._progress_handles


class MailboxHandle:
    _mailbox: "Mailbox"
    _slot: _MailboxSlot
    _on_probe: Optional[Callable[[MailboxProbe], None]]
    _on_progress: Optional[Callable[[MailboxProgress], None]]
    _interface: Optional["InterfaceShared"]
    _keepalive: bool

    def __init__(self, mailbox: "Mailbox", slot: _MailboxSlot) -> None:
        self._mailbox = mailbox
        self._slot = slot
        self._on_probe = None
        self._on_progress = None
        self._interface = None
        self._keepalive = False
        self._keepalive_interval = 5

    def add_probe(self, on_probe: Callable[[MailboxProbe], None]) -> None:
        self._on_probe = on_probe

    def add_progress(self, on_progress: Callable[[MailboxProgress], None]) -> None:
        self._on_progress = on_progress

    def _transport_keepalive_failed(self) -> bool:
        if not self._keepalive:
            return False
        if not self._interface:
            return False
        if not self._interface._transport_failed:
            now = time.time()
            if (
                now
                > self._interface._transport_success_timestamp
                + self._keepalive_interval
            ):
                try:
                    self._interface.publish_keepalive()
                except Exception:
                    self._interface._transport_mark_failed()
                else:
                    self._interface._transport_mark_success()
        return self._interface._transport_failed

    def wait(
        self,
        *,
        timeout: float,
        on_probe: Callable[[MailboxProbe], None] = None,
        on_progress: Callable[[MailboxProgress], None] = None,
        release: bool = True,
    ) -> Optional[pb.Result]:
        probe_handle: Optional[MailboxProbe] = None
        progress_handle: Optional[MailboxProgress] = None
        found: Optional[pb.Result] = None
        start_time = time.time()
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
            if self._transport_keepalive_failed():
                raise MailboxError("transport failed")

            found = self._slot._get_and_clear(timeout=wait_timeout)
            if found:
                # Always update progress to 100% when done
                if on_progress and progress_handle and progress_sent:
                    progress_handle.set_percent_done(100)
                    on_progress(progress_handle)
                break
            now = time.time()
            if timeout >= 0:
                if now >= start_time + timeout:
                    break
            if on_probe and probe_handle:
                on_probe(probe_handle)
            if on_progress and progress_handle:
                if timeout > 0:
                    percent_done = min((now - start_time) / timeout, 1.0)
                progress_handle.set_percent_done(percent_done)
                on_progress(progress_handle)
                progress_sent = True
        if release:
            self._release()
        return found

    def _release(self) -> None:
        self._mailbox._release_slot(self.address)

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
        on_progress: Callable[[MailboxProgress], None] = None,
    ) -> Optional[pb.Result]:
        return handle.wait(timeout=timeout, on_progress=on_progress)

    def wait_all(
        self,
        handles: List[MailboxHandle],
        *,
        timeout: float,
        on_progress_all: Callable[[MailboxProgressAll], None] = None,
    ) -> None:
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

        while handles:
            done_handles = wait_all._get_and_clear(timeout=1)

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

            for handle in done_handles:
                if progress_all_handle:
                    progress_all_handle.remove_progress_handle_matching_handle(handle)
                handles.remove(handle)

        wait_all._clear_handles()

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
