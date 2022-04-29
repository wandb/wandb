"""Reader thread."""

import logging

from . import datastore
from wandb.proto import wandb_internal_pb2  # type: ignore


logger = logging.getLogger(__name__)


class ReadManager:
    def __init__(
        self,
        settings,
        record_q,
        result_q,
        handler_q,
    ):
        self._settings = settings
        self._record_q = record_q
        self._result_q = result_q
        self._handler_q = handler_q
        self._ds = None

    def open(self):
        pass
        # self._ds = datastore.DataStore()
        # self._ds.open_for_write(self._settings.sync_file)

    def read(self, record):
        print("reader read", record)
        # if not self._ds:
        #     self.open()

        # record_type = record.WhichOneof("record_type")
        # assert record_type

        # self._ds.write(record)
        sync_item = record.sync.dir
        print("TRY", sync_item)
        ds = datastore.DataStore()
        try:
            ds.open_for_scan(sync_item)
        except AssertionError as e:
            print(f".wandb file is empty ({e}), skipping: {sync_item}")

        while True:
            data = ds.scan_data()
            if data is None:
                break
            pb = wandb_internal_pb2.Record()
            pb.ParseFromString(data)
            record_type = pb.WhichOneof("record_type")
            print("GOT", record_type)
            self._handler_q.put(pb)


    def finish(self):
        pass

    def debounce(self) -> None:
        pass
