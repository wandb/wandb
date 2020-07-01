#!/usr/bin/env python
# NOTE: Currently this installs pytorch on the various python versions
import sys
from subprocess import call

version = "".join([str(v) for v in sys.version_info[:2]])
if version == "27":
    # Pytorch dropped support for python 2 in 1.5x
    call(["venv/bin/pip", "install", "torch==1.4.0+cpu", "torchvision==0.5.0+cpu", "-f", "https://download.pytorch.org/whl/torch_stable.html"])
else:
    if len(sys.argv) > 1 and sys.argv[1] == "edge":
        call(["venv/bin/pip", "install", "--pre", "torch", "torchvision",
            "-f", "https://download.pytorch.org/whl/nightly/cpu/torch_nightly.html"])
    else:
        call(["venv/bin/pip", "install", "torch==1.5.1+cpu", "torchvision==0.6.1+cpu", "-f", "https://download.pytorch.org/whl/torch_stable.html"])