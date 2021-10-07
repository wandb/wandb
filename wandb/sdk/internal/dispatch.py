"""Dispatch manager (driven by DispatchThread).

Dispatch thread is fed by the handler thread and feeds the sender thread

Details:
  HandlerThread [non-blocking]
    get_from: handler_q
    put_to: dispatch_q
    put_to: response_q

  DispatchThread [blocking on disk]
    get_from: dispatch_q (done_q)
    put_to: send_q
    put_to: response_q

  SendThread [blocking on network]
    get_from: send_q
    put_to: response_q
    put_to: done_q (dispatch_q)
"""

import logging

from . import datastore


logger = logging.getLogger(__name__)


class DispatchManager(object):
    def __init__(
        self, settings, record_q, result_q, sender_q,
    ):
        self._settings = settings
        self._record_q = record_q
        self._result_q = result_q
        self._sender_q = sender_q
        self._ds = None
        self._inflight = 0

    def open(self):
        self._ds = datastore.DataStore()
        self._ds.open_for_write(self._settings.sync_file)

    def _write(self, record):
        if not self._ds:
            self.open()

        record_type = record.WhichOneof("record_type")
        assert record_type

        self._ds.write(record)

    def dispatch(self, record):
        record_type = record.WhichOneof("record_type")
        if record_type == "notify":
            self._inflight -= 1
            return

        if not record.control.local:
            self._write(record)

        # Bulk of work goes here we now know how much data is backed up in the sender
        # if we are backed up, we should add to a backlog queue.
        # this backlog queue can hold either:
        #   1. the record (for any local records that are not persisted)
        #   2. indication of where it is on disk
        # the backlog queue can be implemented itself as an OverflowQueue,  keeping most stuff in memory but falling back to a
        # disk queue
        # the _write function above can return the size of the object so we cand decide based on size rather than record count
        # it probably should return a tuple (filenum, block, offset, size)
        # optimization is to cache the last N blocks of records?
        # do we need hysteresis for the switching between disk backed and memory backed so we dont seek a bunch?
        # eventually datastore should be written as a directory of files.

        if not self._settings._offline or record.control.always_send:
            self._sender_q.put(record)
            self._inflight += 1

    def finish(self):
        if self._ds:
            self._ds.close()

    def debounce(self) -> None:
        pass
