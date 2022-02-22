try:
    # Try to load the Cython performant OrderedDict (C)
    # as is more performant than collections.OrderedDict (Python)
    from cyordereddict import OrderedDict
except ImportError:
    from collections import OrderedDict

__all__ = ['OrderedDict']
