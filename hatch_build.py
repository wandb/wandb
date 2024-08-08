import dataclasses
import os
import pathlib
import platform
import re
import shutil
import sys
import sysconfig
from typing import Any, Dict, List

from hatchling.builders.hooks.plugin.interface import BuildHookInterface
from typing_extensions import override

# A small hack to allow importing build scripts from the source tree.
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from apple_stats import hatch as hatch_apple_stats  # noqa: I001 E402
from core import hatch as hatch_core  # noqa: I001 E402
from nvidia_gpu_stats import hatch as hatch_nvidia_gpu_stats  # noqa: I001 E402

# Necessary inputs for releases.
_WANDB_RELEASE_COMMIT = "WANDB_RELEASE_COMMIT"

# Flags useful for test and debug builds.
_WANDB_BUILD_COVERAGE = "WANDB_BUILD_COVERAGE"
_WANDB_BUILD_GORACEDETECT = "WANDB_BUILD_GORACEDETECT"

# Other build options.
_WANDB_BUILD_UNIVERSAL = "WANDB_BUILD_UNIVERSAL"
_WANDB_BUILD_SKIP_APPLE = "WANDB_BUILD_SKIP_APPLE"
_WANDB_BUILD_SKIP_NVIDIA = "WANDB_BUILD_SKIP_NVIDIA"


class CustomBuildHook(BuildHookInterface):
    @override
    def initialize(self, version: str, build_data: Dict[str, Any]) -> None:
        if self.target_name == "wheel":
            self._prepare_wheel(build_data)

    def _prepare_wheel(self, build_data: Dict[str, Any]) -> None:
        artifacts: list[str] = build_data["artifacts"]

        if self._include_wandb_core():
            artifacts.extend(self._build_wandb_core())

        if self._include_apple_stats():
            artifacts.extend(self._build_apple_stats())

        if self._include_nvidia_gpu_stats():
            artifacts.extend(self._build_nvidia_gpu_stats())

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
        return not self._must_build_universal()

    def _include_apple_stats(self) -> bool:
        """Returns whether we should produce a wheel with apple_gpu_stats."""
        return (
            not self._must_build_universal()
            and not _get_env_bool(_WANDB_BUILD_SKIP_APPLE, default=False)
            and self._target_platform().goos == "darwin"
        )

    def _include_nvidia_gpu_stats(self) -> bool:
        """Returns whether we should produce a wheel with nvidia_gpu_stats."""
        return (
            not _get_env_bool(_WANDB_BUILD_SKIP_NVIDIA, default=False)
            # TODO: Add support for Windows.
            and self._target_platform().goos == "linux"
        )

    def _is_platform_wheel(self) -> bool:
        """Returns whether we're producing a platform-specific wheel."""
        return self._include_wandb_core() or self._include_apple_stats()

    def _build_apple_stats(self) -> List[str]:
        output = pathlib.Path("wandb", "bin", "apple_gpu_stats")

        self.app.display_waiting("Building apple_gpu_stats...")
        hatch_apple_stats.build_applestats(output_path=output)

        return [output.as_posix()]

    def _get_and_require_cargo_binary(self) -> pathlib.Path:
        cargo = shutil.which("cargo")

        if not cargo:
            self.app.abort(
                "Did not find the 'cargo' binary. You need Rust to build wandb"
                " from source. See https://www.rust-lang.org/tools/install.",
            )

        return pathlib.Path(cargo)

    def _build_nvidia_gpu_stats(self) -> List[str]:
        output = pathlib.Path("wandb", "bin", "nvidia_gpu_stats")

        self.app.display_waiting("Building nvidia_gpu_stats Go binary...")
        hatch_nvidia_gpu_stats.build_nvidia_gpu_stats(
            cargo_binary=self._get_and_require_cargo_binary(),
            output_path=output,
        )

        return [output.as_posix()]

    def _git_commit_sha(self) -> str:
        try:
            import subprocess

            src_dir = pathlib.Path(__file__).parent
            commit = (
                subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=src_dir)
                .decode("utf-8")
                .strip()
            )
            return commit
        except Exception:
            return ""

    def _build_wandb_core(self) -> List[str]:
        output = pathlib.Path("wandb", "bin", "wandb-core")

        with_coverage = _get_env_bool(_WANDB_BUILD_COVERAGE, default=False)
        with_race_detection = _get_env_bool(_WANDB_BUILD_GORACEDETECT, default=False)

        plat = self._target_platform()

        self.app.display_waiting("Building wandb-core Go binary...")
        hatch_core.build_wandb_core(
            go_binary=self._get_and_require_go_binary(),
            output_path=output,
            with_code_coverage=with_coverage,
            with_race_detection=with_race_detection,
            wandb_commit_sha=os.getenv(_WANDB_RELEASE_COMMIT) or self._git_commit_sha(),
            target_system=plat.goos,
            target_arch=plat.goarch,
        )

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

    def _target_platform(self) -> "TargetPlatform":
        """Returns the platform we're building for (for cross-compilation)."""
        # Checking sysconfig.get_platform() is the "standard" way of getting the
        # target platform in Python cross-compilation. Build tools like
        # cibuildwheel control its output by setting the undocumented
        # _PYTHON_HOST_PLATFORM environment variable which is also a good way
        # of manually testing this function.
        plat = sysconfig.get_platform()
        match = re.match(
            r"(win|linux|macosx-.+)-(aarch64|arm64|x86_64|amd64)",
            plat,
        )
        if match:
            if match.group(1).startswith("macosx"):
                goos = "darwin"
            elif match.group(1) == "win":
                goos = "windows"
            else:
                goos = match.group(1)

            goarch = _to_goarch(match.group(2))

            return TargetPlatform(
                goos=goos,
                goarch=goarch,
            )

        self.app.display_warning(
            f"Failed to parse sysconfig.get_platform() ({plat}); disabling"
            " cross-compilation.",
        )

        os = platform.system().lower()
        if os in ("windows", "darwin", "linux"):
            goos = os
        else:
            goos = ""

        goarch = _to_goarch(platform.machine().lower())

        return TargetPlatform(
            goos=goos,
            goarch=goarch,
        )


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


@dataclasses.dataclass(frozen=True)
class TargetPlatform:
    goos: str
    goarch: str


def _to_goarch(arch: str) -> str:
    """Returns a valid GOARCH value or the empty string."""
    return {
        # amd64 synonyms
        "amd64": "amd64",
        "x86_64": "amd64",
        # arm64 synonyms
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(arch, "")
