#!/usr/bin/env python

import os
from grpc_tools import protoc  # type: ignore

os.chdir("../..")
protoc.main((
    '',
    '-I', 'vendor/protobuf/src',
    '-I', '.',
    '--python_out=.',
    'wandb/proto/wandb_internal.proto',
    ))
