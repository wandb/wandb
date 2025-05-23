import sys

import pytest

if sys.version_info < (3, 9):
    pytest.skip(
        "Launch is not supported on Python versions < 3.9", allow_module_level=True
    )
