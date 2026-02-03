import dataclasses
import importlib.util
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
from core import hatch as hatch_core
from gpu_stats import hatch as hatch_gpu_stats

# Import arrow-rs-wrapper hatch module dynamically
_arrow_rs_wrapper_hatch_path = (
    pathlib.Path(__file__).parent / "parquet-rust-wrapper" / "hatch.py"
)
_spec = importlib.util.spec_from_file_location(
    "hatch_arrow_rs_wrapper", _arrow_rs_wrapper_hatch_path
)
hatch_arrow_rs_wrapper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hatch_arrow_rs_wrapper)

# Necessary inputs for releases.
_WANDB_RELEASE_COMMIT = "WANDB_RELEASE_COMMIT"

# Flags useful for test and debug builds.
_WANDB_BUILD_COVERAGE = "WANDB_BUILD_COVERAGE"
_WANDB_BUILD_GORACEDETECT = "WANDB_BUILD_GORACEDETECT"

# Other build options.
_WANDB_BUILD_SKIP_GPU_STATS = "WANDB_BUILD_SKIP_GPU_STATS"
_WANDB_BUILD_SKIP_ARROW_RS_WRAPPER = "WANDB_BUILD_SKIP_ARROW_RS_WRAPPER"
_WANDB_ENABLE_CGO = "WANDB_ENABLE_CGO"


class CustomBuildHook(BuildHookInterface):
    @override
    def initialize(self, version: str, build_data: Dict[str, Any]) -> None:
        if self.target_name == "wheel":
            self._prepare_wheel(build_data)
        elif self.target_name == "editable":
            self._prepare_editable(build_data)

    def _prepare_wheel(self, build_data: Dict[str, Any]) -> None:
        build_data["tag"] = f"py3-none-{self._get_platform_tag()}"

        artifacts: list[str] = build_data["artifacts"]
        artifacts.extend(self._build_wandb_core())
        artifacts.extend(self._build_arrow_rs_wrapper())
        if self._include_gpu_stats():
            artifacts.extend(self._build_gpu_stats())

    def _prepare_editable(self, build_data: Dict[str, Any]) -> None:
        """Build native extensions for editable installs.

        For editable installs, we need to build the native extensions and place
        them in the source tree so they can be found at runtime.
        """
        # Build wandb-core and place it in wandb/bin
        self._build_wandb_core()

        # Build arrow-rs-wrapper
        self._build_arrow_rs_wrapper()

        # Build gpu_stats if not skipped
        if self._include_gpu_stats():
            self._build_gpu_stats()

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
        #
        # Accept both macosx_<major>_<minor>_<arch> and macosx_<major>_<arch>.
        macos_match = re.fullmatch(r"macosx_(\d+)(?:_(\d+))?_(\w+)", platform_tag)
        if macos_match:
            major = int(macos_match.group(1))
            arch = macos_match.group(3)
            if major >= 11:
                platform_tag = f"macosx_{major}_0_{arch}"

        return platform_tag

    def _include_gpu_stats(self) -> bool:
        """Returns whether we should produce a wheel with gpu_stats."""
        return not _get_env_bool(_WANDB_BUILD_SKIP_GPU_STATS, default=False)

    def _get_and_require_cargo_binary(self) -> pathlib.Path:
        cargo = shutil.which("cargo")

        # If not in PATH, try the standard Rust installation location
        if not cargo:
            home = pathlib.Path.home()
            cargo_path = home / ".cargo" / "bin" / "cargo"
            if cargo_path.exists():
                cargo = str(cargo_path)

        if not cargo:
            self.app.abort(
                "Did not find the 'cargo' binary. You need Rust to build wandb"
                " from source. See https://www.rust-lang.org/tools/install.",
            )
            raise AssertionError("unreachable")

        return pathlib.Path(cargo)

    def _build_gpu_stats(self) -> List[str]:
        output = pathlib.Path("wandb", "bin", "gpu_stats")
        if self._target_platform().goos == "windows":
            output = output.with_suffix(".exe")

        self.app.display_waiting("Building gpu_stats Rust binary...")
        hatch_gpu_stats.build_gpu_stats(
            cargo_binary=self._get_and_require_cargo_binary(),
            output_path=output,
        )

        return [output.as_posix()]

    def _build_arrow_rs_wrapper(self) -> List[str]:
        """Build the arrow-rs-wrapper dynamic library."""
        plat = self._target_platform()

        if plat.goos == "windows":
            lib_name = "rust_parquet_ffi.dll"
        elif plat.goos == "darwin":
            lib_name = "librust_parquet_ffi.dylib"
        else:
            lib_name = "librust_parquet_ffi.so"

        output = pathlib.Path("wandb", "bin", lib_name)

        self.app.display_waiting("Building arrow-rs-wrapper Rust library...")
        hatch_arrow_rs_wrapper.build_arrow_rs_wrapper(
            cargo_binary=self._get_and_require_cargo_binary(),
            output_path=output,
            target_system=plat.goos,
            target_arch=plat.goarch,
        )

        return [output.as_posix()]

    def _git_commit_sha(self) -> str:
        import subprocess

        src_dir = pathlib.Path(__file__).parent

        try:
            return (
                subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=src_dir)
                .decode("utf-8")
                .strip()
            )
        except Exception:
            return ""

    def _build_wandb_core(self) -> List[str]:
        output = pathlib.Path("wandb", "bin", "wandb-core")

        with_coverage = _get_env_bool(_WANDB_BUILD_COVERAGE, default=False)
        with_race_detection = _get_env_bool(_WANDB_BUILD_GORACEDETECT, default=False)
        with_cgo = _get_env_bool(_WANDB_ENABLE_CGO, default=False)

        plat = self._target_platform()

        self.app.display_waiting("Building wandb-core Go binary...")
        hatch_core.build_wandb_core(
            go_binary=self._get_and_require_go_binary(),
            output_path=output,
            with_code_coverage=with_coverage,
            with_race_detection=with_race_detection,
            with_cgo=with_cgo,
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
            raise AssertionError("unreachable")

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
