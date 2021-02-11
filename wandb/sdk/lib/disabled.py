#


class RunDisabled(str):
    def __init__(self, *args, **kwargs):
        object.__setattr__(self, "___dict", {})

    def __add__(self, other):
        return self

    def __sub__(self, other):
        return self

    def __mul__(self, other):
        return self

    def __truediv__(self, other):
        return self

    def __floordiv__(self, other):
        return self

    def __mod__(self, other):
        return self

    def __pow__(self, other, modulo=None):
        return self

    def __lshift__(self, other):
        return self

    def __rshift__(self, other):
        return self

    def __and__(self, other):
        return self

    def __xor__(self, other):
        return self

    def __or__(self, other):
        return self

    def __iadd__(self, other):
        return self

    def __isub__(self, other):
        return self

    def __imul__(self, other):
        return self

    def __idiv__(self, other):
        return self

    def __ifloordiv__(self, other):
        return self

    def __imod__(self, other):
        return self

    def __ipow__(self, other, modulo=None):
        return self

    def __ilshift__(self, other):
        return self

    def __irshift__(self, other):
        return self

    def __iand__(self, other):
        return self

    def __ixor__(self, other):
        return self

    def __ior__(self, other):
        return self

    def __neg__(self):
        return self

    def __pos__(self):
        return self

    def __abs__(self):
        return self

    def __invert__(self):
        return self

    def __complex__(self):
        return 1 + 0j

    def __int__(self):
        return 1

    def __long__(self):
        return 1

    def __float__(self):
        return 1.0

    def __oct__(self):
        return oct(1)

    def __hex__(self):
        return hex(1)

    def __lt__(self, other):
        return True

    def __le__(self, other):
        return True

    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return True

    def __gt__(self, other):
        return True

    def __ge__(self, other):
        return True

    def __getattr__(self, attr):
        return self[attr]

    def __getitem__(self, key):
        d = object.__getattribute__(self, "___dict")
        try:
            if key in d:
                return d[key]
        except TypeError:
            key = str(key)
            if key in d:
                return d[key]
        dummy = RunDisabled()
        d[key] = dummy
        return dummy

    def __setitem__(self, key, value):
        object.__getattribute__(self, "___dict")[key] = value

    def __setattr__(self, key, value):
        self[key] = value

    def __call__(self, *args, **kwargs):
        return RunDisabled()

    def __len__(self):
        return 1

    def __str__(self):
        return ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return exc_type is None

    def __repr__(self):
        return ""

    def __nonzero__(self):
        return True

    def __bool__(self):
        return True

    def __getstate__(self):
        return 1


class SummaryDisabled(dict):
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

    def __getattr__(self, key):
        return self[key]

    def __getitem__(self, key):
        val = dict.__getitem__(self, key)
        if isinstance(val, dict) and not isinstance(val, SummaryDisabled):
            val = SummaryDisabled(val)
            self[key] = val
        return val
