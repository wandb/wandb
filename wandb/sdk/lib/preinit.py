#
import wandb


class PreInitObject(object):
    def __init__(self, name):
        self._name = name

    def __getitem__(self, key):
        raise wandb.Error(
            'You must call wandb.init() before {}["{}"]'.format(self._name, key)
        )

    def __setitem__(self, key, value):
        raise wandb.Error(
            'You must call wandb.init() before {}["{}"]'.format(self._name, key)
        )

    def __setattr__(self, key, value):
        if not key.startswith("_"):
            raise wandb.Error(
                "You must call wandb.init() before {}.{}".format(self._name, key)
            )
        else:
            return object.__setattr__(self, key, value)

    def __getattr__(self, key):
        if not key.startswith("_"):
            raise wandb.Error(
                "You must call wandb.init() before {}.{}".format(self._name, key)
            )
        else:
            raise AttributeError()


def PreInitCallable(name, destination=None):  # noqa: N802
    def preinit_wrapper(*args, **kwargs):
        raise wandb.Error("You must call wandb.init() before {}()".format(name))

    preinit_wrapper.__name__ = str(name)
    if destination:
        preinit_wrapper.__wrapped__ = destination
        preinit_wrapper.__doc__ = destination.__doc__
    return preinit_wrapper
