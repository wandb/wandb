from abc import ABC, abstractmethod


# from fastai
def delegates(to=None, keep=False):
    "Decorator: replace `**kwargs` in signature with params from `to`"

    def _f(f):
        if to is None:
            to_f, from_f = f.__base__.__init__, f.__init__
        else:
            to_f, from_f = to, f
        sig = inspect.signature(from_f)
        sigd = dict(sig.parameters)
        k = sigd.pop("kwargs")
        s2 = {
            k: v
            for k, v in inspect.signature(to_f).parameters.items()
            if v.default != inspect.Parameter.empty and k not in sigd
        }
        sigd.update(s2)
        if keep:
            sigd["kwargs"] = k
        from_f.__signature__ = sig.replace(parameters=sigd.values())
        return f

    return _f


class Dispatcher(ABC):
    @classmethod
    @abstractmethod
    def from_json(cls, spec):
        pass


def generate_name(length=12):
    # This implementation roughly based this snippet in core
    # https://github.com/wandb/core/blob/master/lib/js/cg/src/utils/string.ts#L39-L44

    import numpy as np

    rand = np.random.random()
    rand = int(str(rand)[2:])
    rand36 = np.base_repr(rand, 36)
    return rand36.lower()[:length]
