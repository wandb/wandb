# /// script
# requires-python = ">=3.8"
# dependencies = [
#   "fire",
#   "wandb",
# ]
# ///
from __future__ import annotations

import fire
import wandb
from wandb.proto import wandb_internal_pb2
from wandb.sdk.internal import datastore


def inspect_wandb_transaction_log(wandb_file: str, pause: bool = False) -> None:
    """Inspect a wandb transaction log file.

    The wandb transaction log file is a leveldb-based append-only transaction log
    that contains the data logged for a W&B run. The data is stored in protocol
    buffer format in the log file run-<run_id>.wandb in the run directory.
    This function will parse the protocol buffer data and print it to the console.

    Args:
        wandb_file: Path to the wandb transaction log file.
        pause: Pause after each record. Defaults to False.
    """

    def _robust_scan(_ds: datastore.DataStore):
        """Attempt to scan data, handling incomplete files."""
        try:
            return _ds.scan_data()
        except AssertionError as e:
            if _ds.in_last_block():
                wandb.termwarn(
                    f".wandb file is incomplete ({e}), be sure to sync this run "
                    "again once it's finished"
                )
                return None
            else:
                raise

    ds = datastore.DataStore()
    try:
        ds.open_for_scan(wandb_file)
    except AssertionError as e:
        print(f".wandb file is empty ({e}), skipping: {wandb_file}")
        return

    while True:
        data = _robust_scan(ds)
        if data is None:
            break
        pb = wandb_internal_pb2.Record()
        pb.ParseFromString(data)
        record_type = pb.WhichOneof("record_type")
        print(f"RECORD TYPE: {record_type}")
        print(pb)
        print()
        if pause:
            input()


if __name__ == "__main__":
    fire.Fire(inspect_wandb_transaction_log)
