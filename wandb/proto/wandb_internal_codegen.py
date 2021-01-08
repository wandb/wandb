#!/usr/bin/env python

import os
import subprocess

import grpc_tools  # type: ignore
from grpc_tools import protoc  # type: ignore


def get_pip_package_version(package):
    out = subprocess.check_output(("pip", "show", package))
    info = dict([l.split(": ", 2) for l in out.decode().rstrip("\n").split("\n")])
    return info["Version"]

def get_requirements_version(requirements_file, package):
    with open(requirements_file) as f:
        lines = f.readlines()
        for l in lines:
            tokens = l.strip().split("==")
            if tokens[0] == package:
                assert len(tokens) == 2, "Package {} not pinned".format(package)
                return tokens[1]
    return

package = "grpcio-tools"
package_version = get_pip_package_version(package)
requirements_file = "../../requirements_build.txt"
requirements_version = get_requirements_version(requirements_file, package)
assert package_version == requirements_version, (
        "Package {} found={} required={}".format(package, package_version, requirements_version))

proto_root = os.path.join(os.path.dirname(grpc_tools.__file__), "_proto")
os.chdir("../..")
protoc.main((
    '',
    '-I', proto_root,
    '-I', '.',
    '--python_out=.',
    '--mypy_out=.',
    'wandb/proto/wandb_internal.proto',
    ))

protoc.main((
    '',
    '-I', proto_root,
    '-I', '.',
    '--python_out=.',
    '--mypy_out=.',
    'wandb/proto/wandb_telemetry.proto',
    ))

protoc.main((
    '',
    '-I', proto_root,
    '-I', '.',
    '--python_out=.',
    '--grpc_python_out=.',
    '--mypy_out=.',
    'wandb/proto/wandb_server.proto',
    ))
