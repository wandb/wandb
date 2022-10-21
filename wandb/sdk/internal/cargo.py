"""Cargo Manager."""

from wandb.proto.wandb_internal_pb2 import Record, Result


class CargoItem:
    def __init__(self) -> None:
        pass


class Cargo:
    def __init__(self) -> None:
        pass

    def track_record(self, record: Record) -> None:
        if not record.control.cancellable:
            return
        pass

    def release_result(self, result: Result) -> None:
        pass
