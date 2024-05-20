import os
import pathlib
import subprocess
from typing import Mapping


def build_libwandb(
    go_binary: pathlib.Path,
    output_path: pathlib.PurePath,
):
    """Builds the wandb client Go module as a shared library.

    Args:
        go_binary: Path to the Go binary, which must exist.
        output_path: The path where to output the shared library and
            the header file, relative to the workspace root.

    """
    output_flags = ["-o", str(".." / output_path)]
    build_mode_flags = ["-buildmode", "c-shared"]
    vendor_flags = ["-mod=mod"]

    subprocess.check_call(
        [
            str(go_binary),
            "build",
            *output_flags,
            *build_mode_flags,
            *vendor_flags,
            str(pathlib.Path("cmd", "client", "main.go")),
        ],
        cwd="client",
        env=_go_env(),
    )


def _go_env() -> Mapping[str, str]:
    """Returns the environment variables for the Go build."""
    env = dict(os.environ)

    env["GOWORK"] = "off"

    return env
