import os
import pathlib
import platform
import re
import sys
import sysconfig
from typing import Any, Dict, List

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

# A small hack to allow importing build scripts from the source tree.
sys.path = [str(pathlib.Path(__file__).parent)] + sys.path
from apple_stats import hatch as hatch_apple_stats  # noqa: I001 E402
from core import hatch as hatch_core  # noqa: I001 E402


_WANDB_BUILD_UNIVERSAL = "WANDB_BUILD_UNIVERSAL"
_WANDB_BUILD_COVERAGE = "WANDB_BUILD_COVERAGE"
_WANDB_RELEASE_COMMIT = "WANDB_RELEASE_COMMIT"


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: Dict[str, Any]) -> None:
        if self.target_name == "wheel":
            self._prepare_wheel(build_data)

    def _prepare_wheel(self, build_data: Dict[str, Any]) -> None:
        artifacts: list[str] = build_data["artifacts"]

        if self._include_wandb_core():
            artifacts.extend(self._build_wandb_core())

        if self._include_apple_stats():
            artifacts.extend(self._build_apple_stats())

        if self._is_platform_wheel():
            # Replace dots, spaces and dashes with underscores following
            # https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/#platform-tag
            platform_tag = re.sub("[-. ]", "_", sysconfig.get_platform())
            build_data["tag"] = f"py3-none-{platform_tag}"

    def _must_build_universal(self) -> bool:
        """Returns whether we must build a universal wheel."""
        return _get_env_bool(_WANDB_BUILD_UNIVERSAL, default=False)

    def _include_wandb_core(self) -> bool:
        """Returns whether we should produce a wheel with wandb-core."""
        return not self._must_build_universal()

    def _include_apple_stats(self) -> bool:
        """Returns whether we should produce a wheel with apple_gpu_stats."""
        return (
            not self._must_build_universal() and platform.system().lower() == "darwin"
        )

    def _is_platform_wheel(self) -> bool:
        """Returns whether we're producing a platform-specific wheel."""
        return self._include_wandb_core() or self._include_apple_stats()

    def _build_apple_stats(self) -> List[str]:
        output = pathlib.Path("wandb", "bin", "apple_gpu_stats")

        self.app.display_waiting("Building apple_gpu_stats...")
        hatch_apple_stats.build_applestats(output_path=output)

        return [output.as_posix()]

    def _build_wandb_core(self) -> List[str]:
        output = pathlib.Path("wandb", "bin", "wandb-core")

        with_coverage = _get_env_bool(_WANDB_BUILD_COVERAGE, default=False)

        self.app.display_waiting("Building wandb-core Go binary...")
        hatch_core.build_wandb_core(
            output_path=output,
            with_code_coverage=with_coverage,
            wandb_commit_sha=os.getenv(_WANDB_RELEASE_COMMIT),
        )

        # NOTE: as_posix() is used intentionally. Hatch expects forward slashes
        # even on Windows.
        return [output.as_posix()]


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
