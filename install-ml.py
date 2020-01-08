#!/usr/bin/env python
# NOTE: This is only being used by the edge-ml test in circle currently
import sys
from subprocess import call

# Edgeml errors were happening because a package named PIL was installed...
call(["venv/bin/pip", "uninstall", "PIL"])
version = "".join([str(v) for v in sys.version_info[:2]])
if version == "27":
    pass
call(["venv/bin/pip", "install", "torch==1.2.0+cpu", "torchvision==0.4.0+cpu",
      "-f", "https://download.pytorch.org/whl/torch_stable.html"])
