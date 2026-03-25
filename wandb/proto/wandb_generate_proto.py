#!/usr/bin/env python
"""Generate Python protobuf bindings using protoc.

Usage (called from nox, with cwd set to wandb/proto):
    python wandb_generate_proto.py --pb-major 5

The --pb-major flag determines the output directory (wandb/proto/v{pb_major}/).
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys

PROTO_FILES = [
    "wandb_base.proto",
    "wandb_internal.proto",
    "wandb_settings.proto",
    "wandb_telemetry.proto",
    "wandb_server.proto",
    "wandb_sync.proto",
    "wandb_api.proto",
]


def find_protoc() -> str:
    """Locate the protoc binary."""
    if protoc := shutil.which("protoc"):
        return protoc

    print("ERROR: protoc not found. Run install-protoc.sh first.", file=sys.stderr)
    sys.exit(1)


def find_mypy_protobuf_plugin() -> str:
    """Locate the protoc-gen-mypy plugin from the mypy-protobuf package."""
    if plugin := shutil.which("protoc-gen-mypy"):
        return plugin

    print(
        "ERROR: protoc-gen-mypy not found. Install mypy-protobuf.",
        file=sys.stderr,
    )
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Python protobuf bindings.")
    parser.add_argument(
        "--pb-major",
        type=int,
        required=True,
        help="Major version of the target protobuf runtime (4, 5, 6, 7).",
    )
    args = parser.parse_args()

    protoc = find_protoc()
    find_mypy_protobuf_plugin()  # ensure it's on PATH for protoc to find

    result = subprocess.run([protoc, "--version"], capture_output=True, text=True)
    print(f"[INFO] Using {protoc}: {result.stdout.strip()}")

    # We expect to be called from wandb/proto/ (via nox session chdir).
    # Change to repo root so proto import paths resolve correctly.
    os.chdir("../..")
    repo_root = pathlib.Path.cwd()

    tmp_out = repo_root / "wandb" / "proto" / f"v{args.pb_major}"
    tmp_out.mkdir(parents=True, exist_ok=True)

    for proto_file in PROTO_FILES:
        cmd = [
            protoc,
            "-I",
            ".",
            f"--python_out={tmp_out}",
            f"--mypy_out={tmp_out}",
            f"wandb/proto/{proto_file}",
        ]
        print(f"[INFO] Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"ERROR: protoc failed for {proto_file}:", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            sys.exit(1)

    # protoc generates files under wandb/proto/ subdirectory inside tmp_out
    # (mirroring the proto import path). Move them up to tmp_out directly.
    nested = tmp_out / "wandb" / "proto"
    if nested.exists():
        for p in nested.glob("*pb2*"):
            dest = tmp_out / p.name
            if dest.exists():
                dest.unlink()
            p.rename(dest)
        # Clean up empty nested dirs.
        shutil.rmtree(tmp_out / "wandb", ignore_errors=True)

    print(f"[INFO] Python protobuf bindings generated in {tmp_out}")


if __name__ == "__main__":
    main()
