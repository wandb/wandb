#!/usr/bin/env python
import sys
from subprocess import call

version = "".join([str(v) for v in sys.version_info[:2]])
if version == "27":
    call(["pip", "install", "http://download.pytorch.org/whl/cpu/torch-0.4.1-cp27-cp27mu-linux_x86_64.whl"])
    call(["pip", "install", "torchvision"])
else:
    call(["pip", "install", "torch_nightly", "-f",
          "https://download.pytorch.org/whl/nightly/cpu/torch_nightly.html"])
    call(["pip", "install", "torchvision-nightly"])
