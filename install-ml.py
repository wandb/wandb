#!/usr/bin/env python
# NOTE: This was only used in circle and is no longer required.
# It's being kept around incase future ml libraries require custom install steps.
import sys
from subprocess import call

version = "".join([str(v) for v in sys.version_info[:2]])
if version == "27":
    pass
    #call(["pip", "install", "https://storage.googleapis.com/tensorflow/linux/cpu/tensorflow-1.12.0-cp27-none-linux_x86_64.whl"])
call(["venv/bin/pip", "install", "torch", "torchvision", "tensorflow"])
