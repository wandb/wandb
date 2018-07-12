#!/usr/bin/env python
import sys
from subprocess import call

version = "".join([str(v) for v in sys.version_info[:2]])
if version == "27":
    call(["pip", "install", "http://download.pytorch.org/whl/cpu/torch-0.4.0-cp27-cp27mu-linux_x86_64.whl"])
else:
    call(["pip", "install",
          "http://download.pytorch.org/whl/cpu/torch-0.4.0-cp{version}-cp{version}m-linux_x86_64.whl".format(version=version)])
