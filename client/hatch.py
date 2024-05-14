import os
import pathlib
import subprocess
from typing import Mapping


def build_libwandb(
    go_binary: pathlib.Path,
    output_path: pathlib.PurePath,
):
    output_flags = ["-o", str(".." / output_path)]
    build_mode_flags = ["-buildmode", "c-shared"]
    vendor_flags = ["-mod=mod"]

    # We have to invoke Go from the directory with go.mod, hence the
    # paths relative to ./core
    subprocess.check_call(
        [
            str(go_binary),
            "build",
            *output_flags,
            *build_mode_flags,
            *vendor_flags,
            str(pathlib.Path("cmd", "client", "main.go")),
        ],
        cwd="./client",
        env=_go_env(),
    )


def _go_env() -> Mapping[str, str]:
    """Returns the environment variables for the Go build."""
    env = dict(os.environ)

    env["GOWORK"] = "off"

    return env
