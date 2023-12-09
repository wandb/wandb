import os
import platform
import subprocess
from distutils import log
from pathlib import Path

from setuptools import setup
from setuptools.command.develop import develop
from wheel.bdist_wheel import bdist_wheel, get_platform

# Package naming
# --------------
#   wandb-core:         Package containing architecture specific code

# wandb-core versioning
# ---------------------
CORE_VERSION = "0.17.0b3"


PACKAGE: str = "wandb_core"
PLATFORMS_TO_BUILD_WITH_CGO = (
    "darwin-arm64",
    "linux-amd64",
)


class WBCoreBase:
    @staticmethod
    def _get_package_path():
        base = Path(__file__).parent / PACKAGE
        print(f"Package path: {base}")
        return base

    def _build_core(self):
        core_path = self._get_package_path()

        src_dir = Path(__file__).parent

        env = os.environ.copy()

        goos = platform.system().lower()
        goarch = platform.machine().lower()
        if goarch == "x86_64":
            goarch = "amd64"
        elif goarch == "aarch64":
            goarch = "arm64"
        elif goarch == "armv7l":
            goarch = "armv6l"

        # build a binary for coverage profiling if the GOCOVERDIR env var is set
        gocover = True if os.environ.get("GOCOVERDIR") else False

        # cgo is needed on:
        #  - arm macs to build the gopsutil dependency,
        #    otherwise several system metrics will be unavailable.
        #  - linux to build the dependencies needed to get GPU metrics.
        if f"{goos}-{goarch}" in PLATFORMS_TO_BUILD_WITH_CGO:
            env["CGO_ENABLED"] = "1"

        os.makedirs(core_path, exist_ok=True)
        commit = (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=src_dir)
            .decode("utf-8")
            .strip()
        )

        ldflags = f"-s -w -X main.commit={commit}"
        if f"{goos}-{goarch}" == "linux-amd64":
            # todo: try llvm's lld linker
            ldflags += ' -extldflags "-fuse-ld=gold -Wl,--weak-unresolved-symbols"'
        cmd = [
            "go",
            "build",
            f"-ldflags={ldflags}",
            "-o",
            str(core_path / "wandb-core"),
            "cmd/core/main.go",
        ]
        if gocover:
            cmd.insert(2, "-cover")
        log.info("Building for {goos}-{goarch}")
        log.info(f"Running command: {' '.join(cmd)}")
        subprocess.check_call(cmd, cwd=src_dir, env=env)

        # on arm macs, copy over the stats monitor binary, if available
        # it is built separately with `nox -s build-apple-stats-monitor` to avoid
        # having to wait for that to build on every run.
        log.info(f"{goos}-{goarch}")
        monitor_path = src_dir / "pkg/monitor/apple/AppleStats"
        log.info(f"monitor_path: {monitor_path}")
        log.info(f"does it exist? {monitor_path.exists()}")
        log.info(
            f"ls of {src_dir / 'pkg/monitor/apple'}: {os.listdir(src_dir / 'pkg/monitor/apple')}"
        )
        log.info(f"core_path: {core_path}")
        if goos == "darwin" and goarch == "arm64":
            monitor_path = src_dir / "pkg/monitor/apple/AppleStats"
            if monitor_path.exists():
                log.info("Copying AppleStats binary")
                subprocess.check_call(["cp", str(monitor_path), str(core_path)])


class WrapDevelop(develop, WBCoreBase):
    def run(self):
        develop.run(self)
        self._build_core()


class WrapBdistWheel(bdist_wheel, WBCoreBase):
    def get_tag(self):
        # Use the default implementation to get python and abi tags
        python, abi = bdist_wheel.get_tag(self)[:2]
        # Use the wheel package function to determine platform tag
        plat_name = get_platform(self.bdist_dir)
        # todo: add MACOSX_DEPLOYMENT_TARGET to support older macs
        return python, abi, plat_name

    def run(self):
        self._build_core()
        bdist_wheel.run(self)


if __name__ == "__main__":
    log.set_verbosity(log.INFO)

    setup(
        name="wandb-core",
        version=CORE_VERSION,
        description="W&B Core Library",
        long_description=open("README.md", encoding="utf-8").read(),
        long_description_content_type="text/markdown",
        packages=[PACKAGE],
        zip_safe=False,
        include_package_data=True,
        license="MIT license",
        python_requires=">=3.6",
        cmdclass={
            "develop": WrapDevelop,
            "bdist_wheel": WrapBdistWheel,
        },
    )
