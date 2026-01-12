from __future__ import annotations

import pathlib
import subprocess


def test_util_import_adds_attribute_to_parent_module():
    script = pathlib.Path(__file__).parent / "util_import_lazy.py"
    subprocess.check_call(["python", str(script)])
