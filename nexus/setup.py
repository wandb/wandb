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
#   wandb-core-nightly: Package created every night based on main branch
#   wandb-core-alpha:   Package used during early development
_WANDB_CORE_ALPHA_ENV = "WANDB_CORE_ALPHA"
_is_wandb_core_alpha = bool(os.environ.get(_WANDB_CORE_ALPHA_ENV))

# Nexus version
# -------------
NEXUS_VERSION = "0.16.0b1"


PACKAGE: str = "wandb_core"
PLATFORMS_TO_BUILD_WITH_CGO = (
    "darwin-arm64",
    "linux-amd64",
)


class NexusBase:
    @staticmethod
    def _get_package_path():
        base = Path(__file__).parent / PACKAGE
        return base

    def _build_nexus(self):
        nexus_path = self._get_package_path()

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

        # cgo is needed on:
        #  - arm macs to build the gopsutil dependency,
        #    otherwise several system metrics will be unavailable.
        #  - linux to build the dependencies needed to get GPU metrics.
        if f"{goos}-{goarch}" in PLATFORMS_TO_BUILD_WITH_CGO:
            env["CGO_ENABLED"] = "1"

        os.makedirs(nexus_path, exist_ok=True)
        commit = (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=src_dir)
            .decode("utf-8")
            .strip()
        )

        ldflags = f"-s -w -X main.commit={commit}"
        if f"{goos}-{goarch}" in PLATFORMS_TO_BUILD_WITH_CGO and goos == "linux":
            ldflags += ' -extldflags "-fuse-ld=gold -Wl,--weak-unresolved-symbols"'
        cmd = (
            "go",
            "build",
            f"-ldflags={ldflags}",
            "-o",
            str(nexus_path / "wandb-nexus"),
            "cmd/nexus/main.go",
        )
        log.info("Building for current platform")
        log.info(f"Running command: {' '.join(cmd)}")
        subprocess.check_call(cmd, cwd=src_dir, env=env)


class WrapDevelop(develop, NexusBase):
    def run(self):
        develop.run(self)
        self._build_nexus()


class WrapBdistWheel(bdist_wheel, NexusBase):
    def get_tag(self):
        # Use the default implementation to get python and abi tags
        python, abi = bdist_wheel.get_tag(self)[:2]
        # Use the wheel package function to determine platform tag
        plat_name = get_platform(self.bdist_dir)
        # todo: add MACOSX_DEPLOYMENT_TARGET to support older macs
        return python, abi, plat_name

    def run(self):
        self._build_nexus()
        bdist_wheel.run(self)


if __name__ == "__main__":
    log.set_verbosity(log.INFO)

    setup(
        name="wandb-core" if not _is_wandb_core_alpha else "wandb-core-alpha",
        version=NEXUS_VERSION,
        description="Wandb core",
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
