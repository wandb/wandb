"""datastore tests."""

from __future__ import print_function

import json
import os

import pytest
import wandb
from wandb.internal import datastore
from wandb.proto import wandb_internal_pb2  # type: ignore


FNAME = "test.dat"

try:
    FileNotFoundError
except NameError:
    FileNotFoundError = OSError


def check(ds, data_sizes=tuple(), expected_records=0, expected_pad=0):
    """Check datastore size after multiple items written."""
    for _, data_size in enumerate(data_sizes):
        ds.write_data(b'\x01' * data_size)
    num = sum(data_sizes) + expected_records * 7 + expected_pad
    ds.close()
    s = os.stat(FNAME)
    assert s.st_size == num


@pytest.fixture()
def with_datastore(request):
    """Fixture which returns an initialized datastore."""
    try:
        os.unlink(FNAME)
    except FileNotFoundError:
        pass
    wandb._set_internal_process()
    s = datastore.DataStore()
    s.open(FNAME)

    def fin():
        os.unlink(FNAME)
    request.addfinalizer(fin)
    return s


def test_proto_write_partial():
    """Serialize a proto into a partial block."""
    data = dict(this=2, that=4)
    json_data = json.dumps(data)
    log = wandb_internal_pb2.LogData(json=json_data)
    rec = wandb_internal_pb2.Record()
    rec.log.CopyFrom(log)

    wandb._set_internal_process()
    s = datastore.DataStore()
    s.open(FNAME)
    s.write(rec)
    s.close()


def test_data_write_full(with_datastore):
    """Write a full block."""
    sizes, records = tuple([32768 - 7]), 1
    check(with_datastore, data_sizes=sizes, expected_records=records)


def test_data_write_overflow(with_datastore):
    """Write one more than we can fit in a block."""
    ds = with_datastore
    ds.write_data(b'\x01' * (32768 - 7 + 1))
    ds.close()
    s = os.stat(FNAME)
    assert s.st_size == 32768 + 7 + 1


def test_data_write_pad(with_datastore):
    """Pad 6 bytes with zeros, then write next record."""
    ds = with_datastore
    ds.write_data(b'\x01' * (32768 - 7 - 6))
    ds.write_data(b'\x02' * (1))
    ds.close()
    s = os.stat(FNAME)
    assert s.st_size == 32768 + 7 + 1


def test_data_write_empty(with_datastore):
    """Write empty record with zero length, then write next record."""
    ds = with_datastore
    ds.write_data(b'\x01' * (32768 - 7 - 7))
    ds.write_data(b'\x02' * (1))
    ds.close()
    s = os.stat(FNAME)
    assert s.st_size == 32768 + 7 + 1


def test_data_write_split(with_datastore):
    """Leave just room for 1 more byte, then try to write 2."""
    ds = with_datastore
    ds.write_data(b'\x01' * (32768 - 7 - 8))
    ds.write_data(b'\x02' * (2))
    ds.close()
    s = os.stat(FNAME)
    assert s.st_size == 32768 + 7 + 1


def test_data_write_split_overflow(with_datastore):
    """Leave just room for 1 more byte, then write a block + 1 byte."""
    ds = with_datastore
    ds.write_data(b'\x01' * (32768 - 7 - 8))
    ds.write_data(b'\x02' * (2 + 32768 - 7))
    ds.close()
    s = os.stat(FNAME)
    assert s.st_size == 32768 * 2 + 7 + 1


def test_data_write_fill(with_datastore):
    """Leave just room for 1 more byte, then write a 1 byte, followed by another 1 byte."""
    sizes, records = tuple([32768 - 7 - 8, 1, 1]), 3
    check(with_datastore, data_sizes=sizes, expected_records=records)
