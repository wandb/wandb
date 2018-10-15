#!/usr/bin/env python
import sys
from subprocess import call

version = "".join([str(v) for v in sys.version_info[:2]])
call(["pip", "install", "torch_nightly", "-f",
      "https://download.pytorch.org/whl/nightly/cpu/torch_nightly.html"])
call(["pip", "install", "torchvision-nightly"])
