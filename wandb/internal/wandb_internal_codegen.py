#!/usr/bin/env python

import os
from grpc_tools import protoc

os.chdir("../..")
protoc.main((
    '',
    '--python_out=.',
    '--grpc_python_out=.',
    'wandb/internal/wandb_internal.proto',
    ))
