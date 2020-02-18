from wandb import wandb_config
from wandb import util
import shortuuid


def generate_id():
    # ~3t run ids (36**8)
    run_gen = shortuuid.ShortUUID(alphabet=list(
        "0123456789abcdefghijklmnopqrstuvwxyz"))
    return run_gen.random(8)


class Run(object):
    def __init__(self, config=None):
        self.config = wandb_config.Config()
        self._backend = None
        self._data = dict()
        self.run_id = generate_id()
        self._step = 0

        if config:
            for k, v in config.items():
                self.config[k] = v

    def _set_backend(self, backend):
        self._backend = backend

    def log(self, data, step=None, commit=True):
        if commit:
            self._data["_step"] = self._step
            self._step += 1
            if self._data:
                self._data.update(data)
                self._backend.log(self._data)
            else:
                self._data.update(data)
                self._backend.log(self._data)
            self._data = dict()
        else:
            self._data.update(data)

    def join(self):
        self._backend.join()
