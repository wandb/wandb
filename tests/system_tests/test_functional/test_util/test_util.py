import pathlib
import subprocess

import pytest


@pytest.mark.wandb_core_only(reason="does not depend on service")
def test_util_import_adds_attribute_to_parent_module():
    script = pathlib.Path(__file__).parent / "util_import_lazy.py"
    subprocess.check_call(["python", str(script)])
