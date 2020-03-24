from __future__ import print_function

from wandb.proto import wandb_internal_pb2  # type: ignore
import struct
import logging

logger = logging.getLogger(__name__)


class DataStore(object):
    def __init__(self):
        self._fp = None
        self._log_type = wandb_internal_pb2.LogData().__class__.__name__
        self._run_type = wandb_internal_pb2.Run().__class__.__name__


    def open(self, fname):
        self._fname = fname
        logger.info("open: %s", fname)
        self._fp = open(fname, "wb")

    def open_for_scan(self, fname):
        self._fname = fname
        logger.info("open for scan: %s", fname)
        self._fp = open(fname, "rb")

    def scan(self):
        header = self._fp.read(4*4)
        if len(header) != 4*4:
            return None
        fields = struct.unpack('<IHHii', header)
        magic, ver, extl, l, rsv = fields
        if extl:
            ext_data = self._fp.read(extl * 4)
            # check len
        data = self._fp.read(l)
        # check len
        return data


    def write(self, obj):
        s = obj.SerializeToString()
        self._fp.write(struct.pack('<IHHII', 0xBBD3AD, 1, 0, len(s), 0))
        self._fp.write(s)

    def write_old(self, obj):
        # TODO(jhr): use https://developers.google.com/protocol-buffers/docs/techniques?csw=1#self-description ?
        r = wandb_internal_pb2.Record()
        r.num = 1
        otype = obj.__class__.__name__
        logtmp = wandb_internal_pb2.LogData()
        # what doesnt instanceof work? guess we need to use proto descriptor or something
        if otype == self._run_type:
            r.run.CopyFrom(obj)
        elif otype == self._log_type:
            r.log.CopyFrom(obj)
        else:
            print("unknown proto", otype, self._log_type)
        s = r.SerializeToString()
        # magic, ver, extralen, len, crc
        self._fp.write(struct.pack('<IHHII', 0xBBD3AD, 1, 0, len(s), 0))
        self._fp.write(s)
        # FIXME(jhr): we dont want this
        #self._fp.flush()

    def close(self):
        if self._fp is not None:
            logger.info("close: %s", self._fname)
            self._fp.close()


def main():
    import sys
    for f in sys.argv[1:]:
        print("file", f)
        ds = DataStore()
        fp = ds.open_for_scan(f)
        while True:
            d = ds.scan()
            if not d:
                break
            print("got", d)


if __name__ == "__main__":
    main()

