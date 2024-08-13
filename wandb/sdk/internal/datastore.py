"""leveldb log datastore.

Format is described at:
    https://github.com/google/leveldb/blob/master/doc/log_format.md

block := record* trailer?
record :=
  checksum: uint32     // crc32c of type and data[] ; little-endian
  length: uint16       // little-endian
  type: uint8          // One of FULL, FIRST, MIDDLE, LAST
  data: uint8[length]

header :=
  ident: char[4]
  magic: uint16
  version: uint8
"""

# TODO: possibly restructure code by porting the C++ or go implementation

import logging
import os
import struct
import zlib
from typing import TYPE_CHECKING, Optional, Tuple

import wandb

if TYPE_CHECKING:
    from typing import IO, Any

    from wandb.proto.wandb_internal_pb2 import Record

logger = logging.getLogger(__name__)

LEVELDBLOG_HEADER_LEN = 7
LEVELDBLOG_BLOCK_LEN = 32768
LEVELDBLOG_DATA_LEN = LEVELDBLOG_BLOCK_LEN - LEVELDBLOG_HEADER_LEN

LEVELDBLOG_FULL = 1
LEVELDBLOG_FIRST = 2
LEVELDBLOG_MIDDLE = 3
LEVELDBLOG_LAST = 4

LEVELDBLOG_HEADER_IDENT = ":W&B"
LEVELDBLOG_HEADER_MAGIC = (
    0xBEE1  # zlib.crc32(bytes("Weights & Biases", 'iso8859-1')) & 0xffff
)
LEVELDBLOG_HEADER_VERSION = 0

try:
    bytes("", "ascii")

    def strtobytes(x):
        """Strtobytes."""
        return bytes(x, "iso8859-1")

    # def bytestostr(x):
    #     return str(x, 'iso8859-1')

except Exception:
    strtobytes = str
    # bytestostr = str


class DataStore:
    _index: int
    _flush_offset: int

    def __init__(self) -> None:
        self._opened_for_scan = False
        self._fp: Optional[IO[Any]] = None
        self._index = 0
        self._flush_offset = 0
        self._size_bytes = 0

        self._crc = [0] * (LEVELDBLOG_LAST + 1)
        for x in range(1, LEVELDBLOG_LAST + 1):
            self._crc[x] = zlib.crc32(strtobytes(chr(x))) & 0xFFFFFFFF

        assert (
            wandb._assert_is_internal_process  # type: ignore
        ), "DataStore can only be used in the internal process"

    def open_for_write(self, fname: str) -> None:
        self._fname = fname
        logger.info("open: %s", fname)
        open_flags = "xb"
        self._fp = open(fname, open_flags)
        self._write_header()

    def open_for_append(self, fname):
        # TODO: implement
        self._fname = fname
        logger.info("open: %s", fname)
        self._fp = open(fname, "wb")
        # do something with _index

    def open_for_scan(self, fname):
        self._fname = fname
        logger.info("open for scan: %s", fname)
        self._fp = open(fname, "r+b")
        self._index = 0
        self._size_bytes = os.stat(fname).st_size
        self._opened_for_scan = True
        self._read_header()

    def seek(self, offset: int) -> None:
        self._fp.seek(offset)  # type: ignore
        self._index = offset

    def get_offset(self) -> int:
        offset = self._fp.tell()  # type: ignore
        return offset

    def in_last_block(self):
        """Determine if we're in the last block to handle in-progress writes."""
        return self._index > self._size_bytes - LEVELDBLOG_DATA_LEN

    def scan_record(self):
        assert self._opened_for_scan, "file not open for scanning"
        # TODO(jhr): handle some assertions as file corruption issues
        # assume we have enough room to read header, checked by caller?
        header = self._fp.read(LEVELDBLOG_HEADER_LEN)
        if len(header) == 0:
            return None
        assert (
            len(header) == LEVELDBLOG_HEADER_LEN
        ), "record header is {} bytes instead of the expected {}".format(
            len(header), LEVELDBLOG_HEADER_LEN
        )
        fields = struct.unpack("<IHB", header)
        checksum, dlength, dtype = fields
        # check len, better fit in the block
        self._index += LEVELDBLOG_HEADER_LEN
        data = self._fp.read(dlength)
        checksum_computed = zlib.crc32(data, self._crc[dtype]) & 0xFFFFFFFF
        assert (
            checksum == checksum_computed
        ), "record checksum is invalid, data may be corrupt"
        self._index += dlength
        return dtype, data

    def scan_data(self):
        # TODO(jhr): handle some assertions as file corruption issues
        # how much left in the block.  if less than header len, read as pad,
        offset = self._index % LEVELDBLOG_BLOCK_LEN
        space_left = LEVELDBLOG_BLOCK_LEN - offset
        if space_left < LEVELDBLOG_HEADER_LEN:
            pad_check = strtobytes("\x00" * space_left)
            pad = self._fp.read(space_left)
            # verify they are zero
            assert pad == pad_check, "invalid padding"
            self._index += space_left

        record = self.scan_record()
        if record is None:  # eof
            return None
        dtype, data = record
        if dtype == LEVELDBLOG_FULL:
            return data

        assert (
            dtype == LEVELDBLOG_FIRST
        ), f"expected record to be type {LEVELDBLOG_FIRST} but found {dtype}"
        while True:
            offset = self._index % LEVELDBLOG_BLOCK_LEN
            record = self.scan_record()
            if record is None:  # eof
                return None
            dtype, new_data = record
            if dtype == LEVELDBLOG_LAST:
                data += new_data
                break
            assert (
                dtype == LEVELDBLOG_MIDDLE
            ), f"expected record to be type {LEVELDBLOG_MIDDLE} but found {dtype}"
            data += new_data
        return data

    def _write_header(self):
        data = struct.pack(
            "<4sHB",
            strtobytes(LEVELDBLOG_HEADER_IDENT),
            LEVELDBLOG_HEADER_MAGIC,
            LEVELDBLOG_HEADER_VERSION,
        )
        assert (
            len(data) == LEVELDBLOG_HEADER_LEN
        ), f"header size is {len(data)} bytes, expected {LEVELDBLOG_HEADER_LEN}"
        self._fp.write(data)
        self._index += len(data)

    def _read_header(self):
        header = self._fp.read(LEVELDBLOG_HEADER_LEN)
        assert (
            len(header) == LEVELDBLOG_HEADER_LEN
        ), "header is {} bytes instead of the expected {}".format(
            len(header), LEVELDBLOG_HEADER_LEN
        )
        ident, magic, version = struct.unpack("<4sHB", header)
        if ident != strtobytes(LEVELDBLOG_HEADER_IDENT):
            raise Exception("Invalid header")
        if magic != LEVELDBLOG_HEADER_MAGIC:
            raise Exception("Invalid header")
        if version != LEVELDBLOG_HEADER_VERSION:
            raise Exception("Invalid header")
        self._index += len(header)

    def _write_record(self, s, dtype=None):
        """Write record that must fit into a block."""
        # double check that there is enough space
        # (this is a precondition to calling this method)
        assert len(s) + LEVELDBLOG_HEADER_LEN <= (
            LEVELDBLOG_BLOCK_LEN - self._index % LEVELDBLOG_BLOCK_LEN
        ), "not enough space to write new records"

        dlength = len(s)
        dtype = dtype or LEVELDBLOG_FULL
        # print("record: length={} type={}".format(dlength, dtype))
        checksum = zlib.crc32(s, self._crc[dtype]) & 0xFFFFFFFF
        # logger.info("write_record: index=%d len=%d dtype=%d",
        #     self._index, dlength, dtype)
        self._fp.write(struct.pack("<IHB", checksum, dlength, dtype))
        if dlength:
            self._fp.write(s)
        self._index += LEVELDBLOG_HEADER_LEN + len(s)

    def _write_data(self, s):
        start_offset = self._index

        offset = self._index % LEVELDBLOG_BLOCK_LEN
        space_left = LEVELDBLOG_BLOCK_LEN - offset
        data_used = 0
        data_left = len(s)
        # logger.info("write_data: index=%d offset=%d len=%d",
        #     self._index, offset, data_left)
        if space_left < LEVELDBLOG_HEADER_LEN:
            pad = "\x00" * space_left
            self._fp.write(strtobytes(pad))
            self._index += space_left
            offset = 0
            space_left = LEVELDBLOG_BLOCK_LEN

        # does it fit in first (possibly partial) block?
        if data_left + LEVELDBLOG_HEADER_LEN <= space_left:
            self._write_record(s)
        else:
            # write first record (we could still be in the middle of a block,
            # but this write will end on a block boundary)
            data_room = space_left - LEVELDBLOG_HEADER_LEN
            self._write_record(s[:data_room], LEVELDBLOG_FIRST)
            data_used += data_room
            data_left -= data_room
            assert data_left, "data_left should be non-zero"

            # write middles (if any)
            while data_left > LEVELDBLOG_DATA_LEN:
                self._write_record(
                    s[data_used : data_used + LEVELDBLOG_DATA_LEN],
                    LEVELDBLOG_MIDDLE,
                )
                data_used += LEVELDBLOG_DATA_LEN
                data_left -= LEVELDBLOG_DATA_LEN

            # write last and flush the entire block to disk
            self._write_record(s[data_used:], LEVELDBLOG_LAST)
            self._fp.flush()
            os.fsync(self._fp.fileno())
            self._flush_offset = self._index

        return start_offset, self._index, self._flush_offset

    def ensure_flushed(self, off: int) -> None:
        self._fp.flush()  # type: ignore

    def write(self, obj: "Record") -> Tuple[int, int, int]:
        """Write a protocol buffer.

        Arguments:
            obj: Protocol buffer to write.

        Returns:
            (start_offset, end_offset, flush_offset) if successful,
            None otherwise

        """
        raw_size = obj.ByteSize()
        s = obj.SerializeToString()
        assert len(s) == raw_size, "invalid serialization"
        ret = self._write_data(s)
        return ret

    def close(self) -> None:
        if self._fp is not None:
            logger.info("close: %s", self._fname)
            self._fp.close()
