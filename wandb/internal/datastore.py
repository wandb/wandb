import wandb_internal_pb2


class DataStore(object):
    def __init__(self):
        self._fp = None
        self._log_type = wandb_internal_pb2.LogData().__class__.__name__
        self._run_type = wandb_internal_pb2.Run().__class__.__name__


    def open(self, fname):
        self._fname = fname
        print("open", fname)
        self._fp = open(fname, "wb")


    def write(self, obj):
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
        self._fp.write(s)
        # FIXME(jhr): we dont want this
        self._fp.flush()

    def close(self):
        if self._fp is not None:
            print("close", self._fname)
            self._fp.close()
