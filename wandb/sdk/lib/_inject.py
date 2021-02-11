#

import wandb


def communicate(rec) -> bool:
    return False


class InjectUtil:
    def __init__(self) -> None:
        self._communicate = communicate
        wandb._INJECT = True

    def install(self, fn):
        global communicate
        communicate = fn

    def cleanup(self):
        self.install(self._communicate)
        wandb._INJECT = False
