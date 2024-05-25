import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
from typing import Any, Dict, List

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

# A small hack to allow importing build scripts from the source tree.
sys.path = [str(pathlib.Path(__file__).parent.parent.parent.parent.parent.parent)] + sys.path
from apple_stats import hatch as hatch_apple_stats  # noqa: I001 E402
from core import hatch as hatch_core  # noqa: I001 E402


_WANDB_BUILD_UNIVERSAL = "WANDB_BUILD_UNIVERSAL"
_WANDB_BUILD_COVERAGE = "WANDB_BUILD_COVERAGE"
_WANDB_BUILD_SKIP_APPLE = "WANDB_BUILD_SKIP_APPLE"
_WANDB_RELEASE_COMMIT = "WANDB_RELEASE_COMMIT"


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: Dict[str, Any]) -> None:
        if self.target_name == "wheel":
            self._prepare_wheel(build_data)

    def _prepare_wheel(self, build_data: Dict[str, Any]) -> None:
        artifacts: list[str] = build_data["artifacts"]

        if self._include_wandb_core():
            artifacts.extend(self._build_wandb_core())

        if self._include_lib_wandb_core():
            artifacts.extend(self._build_lib_wandb_core())

        if self._include_apple_stats():
            artifacts.extend(self._build_apple_stats())

        if self._include_proto():
            artifacts.extend(self._build_proto())

        if self._is_platform_wheel():
            build_data["tag"] = f"py3-none-{self._get_platform_tag()}"

    def _get_platform_tag(self) -> str:
        """Returns the platform tag for the current platform."""
        # Replace dots, spaces and dashes with underscores following
        # https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/#platform-tag
        platform_tag = re.sub("[-. ]", "_", sysconfig.get_platform())

        # On macOS versions >=11, pip expects the minor version to be 0:
        #   https://github.com/pypa/packaging/issues/435
        #
        # You can see the list of tags that pip would support on your machine
        # using `pip debug --verbose`. On my macOS, get_platform() returns
        # 14.1, but `pip debug --verbose` reports only these py3 tags with 14:
        #
        # * py3-none-macosx_14_0_arm64
        # * py3-none-macosx_14_0_universal2
        #
        # We do this remapping here because otherwise, it's possible for `pip wheel`
        # to successfully produce a wheel that you then cannot `pip install` on the
        # same machine.
        macos_match = re.fullmatch(r"macosx_(\d+_\d+)_(\w+)", platform_tag)
        if macos_match:
            major, _ = macos_match.group(1).split("_")
            if int(major) >= 11:
                arch = macos_match.group(2)
                platform_tag = f"macosx_{major}_0_{arch}"

        return platform_tag

    def _must_build_universal(self) -> bool:
        """Returns whether we must build a universal wheel."""
        return _get_env_bool(_WANDB_BUILD_UNIVERSAL, default=False)

    def _include_wandb_core(self) -> bool:
        """Returns whether we should produce a wheel with wandb-core."""
        return False

    def _include_lib_wandb_core(self) -> bool:
        """Returns whether we should produce a wheel with wandb-core."""
        return True

    def _include_proto(self) -> bool:
        """Returns whether we should produce a wheel with generated proto files."""
        return True

    def _include_apple_stats(self) -> bool:
        """Returns whether we should produce a wheel with apple_gpu_stats."""
        return (
            not self._must_build_universal()
            and not _get_env_bool(_WANDB_BUILD_SKIP_APPLE, default=False)
            and platform.system().lower() == "darwin"
        )

    def _is_platform_wheel(self) -> bool:
        """Returns whether we're producing a platform-specific wheel."""
        return self._include_wandb_core() or self._include_lib_wandb_core() or self._include_apple_stats()

    def _build_apple_stats(self) -> List[str]:
        output = pathlib.Path("wandb", "bin", "apple_gpu_stats")

        self.app.display_waiting("Building apple_gpu_stats...")
        hatch_apple_stats.build_applestats(output_path=output)

        return [output.as_posix()]

    def _build_proto(self) -> List[str]:
        proto_files = [
            "wandb_base.proto",
            "wandb_internal.proto",
            "wandb_telemetry.proto",
            "wandb_settings.proto",
            "wandb_server.proto",
        ]
        output_dir = str(pathlib.Path(__file__).parent)
        current_dir = pathlib.Path.cwd()
        os.chdir(str(pathlib.Path(__file__).parent.parent.parent.parent.parent.parent))
        output_files = []
        for file in proto_files:
            output_file = str(pathlib.Path("wandb") / "proto" / file)
            subprocess.check_call(
                [
                    "protoc",
                    "-I=.",
                    f"--python_out={output_dir}",
                    output_file,
                ],
            )
            output_files.append(output_file)
        os.chdir(current_dir)
        return output_files

    def _build_lib_wandb_core(self) -> List[str]:
        subprocess.check_call(
            [ "bash",
              "hatch_build_lib.sh"
              ])
        return [str(pathlib.Path("wandb") / "lib" / "libwandb_core.so")]

    def _build_wandb_core(self) -> List[str]:
        current_dir = pathlib.Path.cwd()
        output = pathlib.Path("wandb", "bin", "wandb-core")

        with_coverage = _get_env_bool(_WANDB_BUILD_COVERAGE, default=False)

        self.app.display_waiting("Building wandb-core Go binary...")
        os.chdir(str(pathlib.Path(__file__).parent.parent.parent.parent.parent.parent))
        hatch_core.build_wandb_core(
            go_binary=self._get_and_require_go_binary(),
            output_path=current_dir / output,
            with_code_coverage=with_coverage,
            wandb_commit_sha=os.getenv(_WANDB_RELEASE_COMMIT),
        )
        os.chdir(current_dir)

        # NOTE: as_posix() is used intentionally. Hatch expects forward slashes
        # even on Windows.
        return [output.as_posix()]

    def _get_and_require_go_binary(self) -> pathlib.Path:
        go = shutil.which("go")

        if not go:
            self.app.abort(
                "Did not find the 'go' binary. You need Go to build wandb"
                " from source. See https://go.dev/doc/install.",
            )

        return pathlib.Path(go)


def _get_env_bool(name: str, default: bool) -> bool:
    """Returns the value of a boolean environment variable."""
    value = os.getenv(name)

    if value is None:
        return default
    elif value.lower() in ("1", "true"):
        return True
    elif value.lower() in ("0", "false"):
        return False
    else:
        raise ValueError(
            f"Environment variable '{name}' has invalid value '{value}'"
            " expected one of {1,true,0,false}."
        )
