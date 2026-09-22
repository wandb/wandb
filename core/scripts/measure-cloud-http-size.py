#!/usr/bin/env python3
"""Compare SDK and shared HTTP cloud clients using release build flags."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goos", default="linux")
    parser.add_argument("--goarch", default="amd64")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    core = Path(__file__).resolve().parents[1]
    output = (
        args.output_dir.resolve()
        if args.output_dir
        else Path(tempfile.mkdtemp(prefix="wandb-cloud-http-size-"))
    )
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, GOOS=args.goos, GOARCH=args.goarch, CGO_ENABLED="0")
    sizes = {}
    for variant in ("sdk", "http"):
        tags = "disable_grpc_modules parquet_read_only"
        if variant == "http":
            tags += " cloud_http"
        binary = output / f"wandb-core-{variant}-{args.goos}-{args.goarch}"
        subprocess.run(
            [
                "go",
                "build",
                "-mod=vendor",
                f"-tags={tags}",
                "-ldflags=-s -w -X main.commit=unknown",
                "-o",
                str(binary),
                "cmd/wandb-core/main.go",
            ],
            cwd=core,
            env=env,
            check=True,
        )
        sizes[variant] = binary.stat().st_size
    result = {
        "toolchain": subprocess.check_output(["go", "version"], text=True).strip(),
        "goos": args.goos,
        "goarch": args.goarch,
        "bytes": sizes,
        "saved_bytes": sizes["sdk"] - sizes["http"],
        "output_dir": str(output),
        "tensorboard_cloud_drivers": {
            "sdk": "Go CDK storage SDK drivers",
            "http": "shared artifact HTTP clients",
        },
    }
    (output / "measurements.json").write_text(json.dumps(result, indent=2) + "\n")
    sys.stdout.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
