#!/usr/bin/env python

import importlib.metadata
import os
import pathlib

import grpc_tools  # type: ignore
from grpc_tools import protoc  # type: ignore
from packaging import version


def get_pip_package_version(package_name: str) -> str:
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        raise ValueError(f"Package `{package_name}` not found")

protobuf_version = version.Version(get_pip_package_version("protobuf"))

proto_root = os.path.join(os.path.dirname(grpc_tools.__file__), "_proto")
tmp_out: pathlib.Path = pathlib.Path(f"wandb/proto/v{protobuf_version.major}/")

os.chdir("../..")
for proto_file in [
    "wandb_base.proto",
    "wandb_internal.proto",
    "wandb_settings.proto",
    "wandb_telemetry.proto",
    "wandb_server.proto",
]:
    ret = protoc.main(
        (
            "",
            "-I",
            proto_root,
            "-I",
            ".",
            f"--python_out={tmp_out}",
            f"--mypy_out={tmp_out}",
            f"wandb/proto/{proto_file}",
        )
    )
    assert not ret

# clean up tmp dirs
for p in (tmp_out / "wandb" / "proto").glob("*pb2*"):
    p.rename(tmp_out / p.name)
os.rmdir(tmp_out / "wandb" / "proto")
os.rmdir(tmp_out / "wandb")
