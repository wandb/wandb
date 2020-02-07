from wandb import wandb_config
from wandb import util
import shortuuid


def generate_id():
    # ~3t run ids (36**8)
    run_gen = shortuuid.ShortUUID(alphabet=list(
        "0123456789abcdefghijklmnopqrstuvwxyz"))
    return run_gen.random(8)


class Run(object):
    def __init__(self, config=None, _backend=None):
        self.config = wandb_config.Config()
        self._backend = _backend
        self._data = dict()
        self.run_id = generate_id()

        if config:
            for k, v in config.items():
                self.config[k] = v

    def log(self, data, commit=True):
        if commit:
            if self._data:
                self._data.update(data)
                self._backend.log(self._data)
                self._data = dict()
            else:
                self._backend.log(data)
        else:
            self._data.update(data)

    def join(self):
        self._backend.join()
