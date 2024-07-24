import fire
import wandb
from wandb.proto import wandb_internal_pb2
from wandb.sdk.internal import datastore


def _robust_scan(ds):
    """Attempt to scan data, handling incomplete files."""
    try:
        return ds.scan_data()
    except AssertionError as e:
        if ds.in_last_block():
            wandb.termwarn(
                f".wandb file is incomplete ({e}), be sure to sync this run again once it's finished"
            )
            return None
        else:
            raise e


def run(
    wandb_file: str,
    pause: bool = False,
) -> None:
    ds = datastore.DataStore()
    try:
        ds.open_for_scan(wandb_file)
    except AssertionError as e:
        print(f".wandb file is empty ({e}), skipping: {wandb_file}")
        return

    # save exit for final send
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
    fire.Fire(run)
