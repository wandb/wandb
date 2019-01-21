#!/usr/bin/env python
import sys
from subprocess import call

version = "".join([str(v) for v in sys.version_info[:2]])
if version == "27":
    call(["pip", "install", "https://storage.googleapis.com/tensorflow/linux/cpu/tensorflow-1.12.0-cp27-none-linux_x86_64.whl"])
call(["pip", "install", "torch", "torchvision", "tensorflow"])
