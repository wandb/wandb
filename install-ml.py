#!/usr/bin/env python
import sys
from subprocess import call

version = "".join([str(v) for v in sys.version_info[:2]])
if version == "27":
    pass
call(["pip", "install", "torch", "torchvision", "tensorflow"])
