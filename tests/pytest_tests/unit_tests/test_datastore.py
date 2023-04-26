"""datastore tests."""


import json
import os

import pytest
import wandb
from wandb.proto import wandb_internal_pb2  # type: ignore

datastore = wandb.wandb_sdk.internal.datastore


FNAME = "test.dat"

try:
    FileNotFoundError  # noqa: B018
except NameError:
    FileNotFoundError = OSError


def check(
    ds,
    chunk_sizes=tuple(),
    expected_records=0,
    expected_pad=0,
    expected_record_sizes=None,
):
    """Check datastore size after multiple items written."""
    record_sizes = []
    for _, chunk_size in enumerate(chunk_sizes):
        size = ds._write_data(b"\x01" * chunk_size)
        record_sizes.append(size)
    num = 7 + sum(chunk_sizes) + expected_records * 7 + expected_pad
    ds.close()
    s = os.stat(FNAME)
    assert s.st_size == num
    if expected_record_sizes is not None:
        assert tuple(record_sizes) == expected_record_sizes


@pytest.fixture()
def with_datastore(request):
    """Fixture which returns an initialized datastore."""
    try:
        os.unlink(FNAME)
    except FileNotFoundError:
        pass
    wandb._set_internal_process()
    s = datastore.DataStore()
    s.open_for_write(FNAME)

    def fin():
        os.unlink(FNAME)

    request.addfinalizer(fin)
    return s


def test_proto_write_partial():
    """Serialize a proto into a partial block."""
    data = dict(this=2, that=4)
    history = wandb_internal_pb2.HistoryRecord()
    for k, v in data.items():
        json_data = json.dumps(v)
        item = history.item.add()
        item.key = k
        item.value_json = json_data
    rec = wandb_internal_pb2.Record()
    rec.history.CopyFrom(history)

    wandb._set_internal_process()
    s = datastore.DataStore()
    s.open_for_write(FNAME)
    s.write(rec)
    s.close()
