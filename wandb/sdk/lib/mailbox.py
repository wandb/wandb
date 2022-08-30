"""
mailbox.
"""

import secrets
import string
import threading
import time
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

from wandb.proto import wandb_internal_pb2 as pb

if TYPE_CHECKING:
    from wandb.sdk.interface.interface_shared import InterfaceShared


def _generate_address(length: int = 12) -> str:
    address = "".join(
        secrets.choice(string.ascii_lowercase + string.digits) for i in range(length)
    )
    return address


class MailboxError(Exception):
    """Generic Mailbox Exception"""

    pass


class _MailboxSlot:
    _result: Optional[pb.Result]
    _event: threading.Event
    _lock: threading.Lock
    _address: str

    def __init__(self, address: str) -> None:
        self._result = None
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._address = address

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


class MailboxProbe:
    def __init__(self) -> None:
        self._handle = None
        self._result = None

    def set_probe_result(self, result) -> None:
        self._result = result

    def get_probe_result(self) -> None:
        return self._result

    def get_mailbox_handle(self) -> None:
        return self._handle

    def set_mailbox_handle(self, handle) -> None:
        self._handle = handle


class MailboxProgress:
    _percent_done: float

    def __init__(self) -> None:
        self._percent_done = 0.0
        self._probe_handles = []

    @property
    def percent_done(self) -> float:
        return self._percent_done

    def set_percent_done(self, percent_done: float) -> None:
        self._percent_done = percent_done

    def add_probe_handle(self, probe_handle: MailboxProbe):
        self._probe_handles.append(probe_handle)

    def get_probe_handles(self):
        return self._probe_handles


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
        found: Optional[pb.Result] = None
        start_time = time.time()
        percent_done = 0.0
        progress_sent = False
        wait_timeout = 1.0
        if timeout >= 0:
            wait_timeout = min(timeout, wait_timeout)

        on_progress = on_progress or self._on_progress
        if on_progress:
            progress_handle = MailboxProgress()

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
        on_progress_all: Callable[[MailboxProgress], None] = None,
    ) -> None:
        for handle in handles:
            _ = handle.wait(timeout=-1, on_progress=on_progress_all)

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
