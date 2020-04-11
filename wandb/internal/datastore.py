"""leveldb log datastore.

Format is described at:
    https://github.com/google/leveldb/blob/master/doc/log_format.md

block := record* trailer?
record :=
  checksum: uint32     // crc32c of type and data[] ; little-endian
  length: uint16       // little-endian
  type: uint8          // One of FULL, FIRST, MIDDLE, LAST
  data: uint8[length]

""" 
from __future__ import print_function

import zlib

import wandb
from wandb.proto import wandb_internal_pb2  # type: ignore
import struct
import logging
import zlib

logger = logging.getLogger(__name__)

LEVELDBLOG_HEADER_LEN = 7
LEVELDBLOG_BLOCK_LEN = 32768
LEVELDBLOG_DATA_LEN = LEVELDBLOG_BLOCK_LEN - LEVELDBLOG_HEADER_LEN

LEVELDBLOG_FULL = 1
LEVELDBLOG_FIRST = 2
LEVELDBLOG_MIDDLE = 3
LEVELDBLOG_LAST = 4

try:
    bytes('', 'ascii')
    def strtobytes(x): return bytes(x, 'iso8859-1')
    def bytestostr(x): return str(x, 'iso8859-1')
except:
    strtobytes = str
    bytestostr = str


class DataStore(object):

    def __init__(self):
        self._opened_for_scan = False
        self._fp = None
        self._log_type = wandb_internal_pb2.LogData().__class__.__name__
        self._run_type = wandb_internal_pb2.Run().__class__.__name__
        self._index = 0

        self._crc = [0] * (LEVELDBLOG_LAST + 1)
        for x in range(1, LEVELDBLOG_LAST + 1):
            self._crc[x] = zlib.crc32(strtobytes(chr(x))) & 0xFFFFFFFF

        assert wandb._IS_INTERNAL_PROCESS

    def open(self, fname):
        self._fname = fname
        logger.info("open: %s", fname)
        self._fp = open(fname, "wb")

    def open_for_append(self, fname):
        # TODO: implement
        self._fname = fname
        logger.info("open: %s", fname)
        self._fp = open(fname, "wb")
        # do something with _index

    def open_for_scan(self, fname):
        self._fname = fname
        logger.info("open for scan: %s", fname)
        self._fp = open(fname, "rb")
        self._index = 0
        self._opened_for_scan = True

    def scan_record(self):
        assert self._opened_for_scan
        # FIXME: if end of block, deal with up to 6 zero bytes
        header = self._fp.read(LEVELDBLOG_HEADER_LEN)
        if len(header) != LEVELDBLOG_HEADER_LEN:
            return None
        fields = struct.unpack('<IHB', header)
        checksum, dlength, dtype = fields
        data = self._fp.read(dlength)
        # check len
        return data

    def scan_block(self):
        pass

    def scan(self):
        # how much left in the block.  if less than header len, read as pad, verify they are zero
        pass

    def _write_record(self, s, dtype=None):
        """Records must fit into a block."""
        # make sure there is enough space
        offset = self._index % LEVELDBLOG_BLOCK_LEN
        space_left = LEVELDBLOG_BLOCK_LEN - offset
        assert len(s) + LEVELDBLOG_HEADER_LEN <= space_left
        checksum = 0
        dlength = len(s)
        dtype = dtype or LEVELDBLOG_FULL
        # print("record: length={} type={}".format(dlength, dtype))
        checksum = zlib.crc32(s, self._crc[dtype]) & 0xFFFFFFFF
        self._fp.write(struct.pack('<IHB', checksum, dlength, dtype))
        if dlength:
            self._fp.write(s)
        self._index += LEVELDBLOG_HEADER_LEN + len(s)

    def write_data(self, s):
        offset = self._index % LEVELDBLOG_BLOCK_LEN
        space_left = LEVELDBLOG_BLOCK_LEN - offset
        written = 0
        data_left = len(s)
        if space_left < LEVELDBLOG_HEADER_LEN:
            pad = '\x00' * space_left
            self._fp.write(strtobytes(pad))
            self._index += space_left
            # print("zero pad (zize={})".format(len(space_left)))
            offset = 0
            space_left = LEVELDBLOG_BLOCK_LEN

        # does it fit in first (possibly partial) block?
        if data_left + LEVELDBLOG_HEADER_LEN <= space_left:
            self._write_record(s)
            return

        # write first record (we could still be in the middle of a block, but we will end on a block boundary)
        data_room = space_left - LEVELDBLOG_HEADER_LEN
        self._write_record(s[:data_room], LEVELDBLOG_FIRST)
        written += data_room
        data_left -= data_room
        assert data_left

        # write middles (if any)
        while data_left > LEVELDBLOG_DATA_LEN:
            self._write_record(s[written:written + LEVELDBLOG_DATA_LEN], LEVELDBLOG_MIDDLE)
            written += LEVELDBLOG_DATA_LEN
            data_left -= LEVELDBLOG_DATA_LEN

        # write last
        self._write_record(s[written:], LEVELDBLOG_LAST)

    def write(self, obj):
        raw_size = obj.ByteSize()
        s = obj.SerializeToString()
        assert len(s) == raw_size
        self.write_data(s)

    def close(self):
        if self._fp is not None:
            logger.info("close: %s", self._fname)
            self._fp.close()
