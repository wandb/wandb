# serves as a pass through
from collections import *
from collections import __all__

# If abc is not present (< 3.3), then
# make sure it is.
if not hasattr(locals(), "abc"):
    from . import abc

    __all__.append("abc")
