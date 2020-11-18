from __future__ import print_function

import fastparquet
import pandas as pd
import queue

from .. import Artifact


# Writes history to parquet files and saves them as artifacts.
class HistoryWriter(object):
    def __init__(self, settings, interface, run_proto):
        self._settings = settings
        self._interface = interface
        self._parq_flush_q = queue.Queue()
        self._parq_record_limit = 100
        self._parq_seq_num = 1
        self._artifact = Artifact(".history", type="history")
        self._run_proto = run_proto

    def write(self, record):
        assert isinstance(record, dict), "Records passed to HistoryWriter must be dicts"

        self._parq_flush_q.put(record)

        # TODO: Move this into a separate thread.
        if not self._run_proto:
            return

        if self._parq_flush_q.qsize() >= self._parq_record_limit:
            self._parq_record_limit *= 2
            self.flush()

    def finish(self):
        if not self._run_proto:
            return

        self.flush()
        # TODO Move this to sender so it can be part of the shutdown state machine.
        self._interface._publish_artifact(self._run_proto, self._artifact, ["latest"])

    def flush(self):
        records = []
        while True:
            try:
                record = self._parq_flush_q.get(block=False)
                records.append(record)
            except queue.Empty:
                break

        if not records:
            return

        records = [r for r in records if "_step" in r]
        df = pd.DataFrame(records, index=[r["_step"] for r in records])
        fname = self._settings.history_file_template.format(seq_num=self._parq_seq_num)
        fastparquet.write(
            fname,
            df,
            compression="GZIP",
        )
        self._artifact.add_file(fname)
        self._parq_seq_num += 1
