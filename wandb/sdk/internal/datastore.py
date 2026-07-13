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

from __future__ import annotations

import logging
import os
import struct
import zlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import IO, Any

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

except Exception:
    strtobytes = str


class DataStore:
    _index: int
    _flush_offset: int

    def __init__(self) -> None:
        self._opened_for_scan = False
        self._fp: IO[Any] | None = None
        self._index = 0
        self._flush_offset = 0
        self._size_bytes = 0

        self._crc = [0] * (LEVELDBLOG_LAST + 1)
        for x in range(1, LEVELDBLOG_LAST + 1):
            self._crc[x] = zlib.crc32(strtobytes(chr(x))) & 0xFFFFFFFF

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
        assert len(header) == LEVELDBLOG_HEADER_LEN, (
            f"record header is {len(header)} bytes instead of the expected {LEVELDBLOG_HEADER_LEN}"
        )
        fields = struct.unpack("<IHB", header)
        checksum, dlength, dtype = fields
        # check len, better fit in the block
        self._index += LEVELDBLOG_HEADER_LEN
        data = self._fp.read(dlength)
        checksum_computed = zlib.crc32(data, self._crc[dtype]) & 0xFFFFFFFF
        assert checksum == checksum_computed, (
            "record checksum is invalid, data may be corrupt"
        )
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

        assert dtype == LEVELDBLOG_FIRST, (
            f"expected record to be type {LEVELDBLOG_FIRST} but found {dtype}"
        )
        while True:
            offset = self._index % LEVELDBLOG_BLOCK_LEN
            record = self.scan_record()
            if record is None:  # eof
                return None
            dtype, new_data = record
            if dtype == LEVELDBLOG_LAST:
                data += new_data
                break
            assert dtype == LEVELDBLOG_MIDDLE, (
                f"expected record to be type {LEVELDBLOG_MIDDLE} but found {dtype}"
            )
            data += new_data
        return data

    def _read_header(self):
        header = self._fp.read(LEVELDBLOG_HEADER_LEN)
        assert len(header) == LEVELDBLOG_HEADER_LEN, (
            f"header is {len(header)} bytes instead of the expected {LEVELDBLOG_HEADER_LEN}"
        )
        ident, magic, version = struct.unpack("<4sHB", header)
        if ident != strtobytes(LEVELDBLOG_HEADER_IDENT):
            raise Exception("Invalid header")
        if magic != LEVELDBLOG_HEADER_MAGIC:
            raise Exception("Invalid header")
        if version != LEVELDBLOG_HEADER_VERSION:
            raise Exception("Invalid header")
        self._index += len(header)

    def close(self) -> None:
        if self._fp is not None:
            logger.info("close: %s", self._fname)
            self._fp.close()
