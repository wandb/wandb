"""
Nexus setup.

To build the nexus wheel only for a specific platform, run:
python -m build -w -n ./nexus --config-setting=--build-option=--nexus-build=darwin-arm64,linux-amd64

To build the nexus wheel for all platforms, run:
python -m build -w -n ./nexus

To install the nexus wheel, run:
pip install --force-reinstall ./nexus/dist/wandb_core-*-py3-none-any.whl
"""

import os
import platform
import subprocess
from distutils import log
from distutils.command.install import install
from pathlib import Path

from setuptools import setup
from setuptools.command.develop import develop

from wheel.bdist_wheel import bdist_wheel

# Package naming
# --------------
#   wandb-core:         Package containing architecture specific code
#   wandb-core-nightly: Package created every night based on main branch
#   wandb-core-alpha:   Package used during early development
_WANDB_CORE_ALPHA_ENV = "WANDB_CORE_ALPHA"
_is_wandb_core_alpha = bool(os.environ.get(_WANDB_CORE_ALPHA_ENV))


PACKAGE: str = "wandb_core"
ALL_PLATFORMS = (
    ("darwin", "arm64", True),
    ("darwin", "amd64", False),
    ("linux", "amd64", True),
    ("windows", "amd64", False),
)

log.set_verbosity(log.INFO)


class NexusBase:
    def _get_package_path(self):
        base = Path(self.install_platlib) / PACKAGE
        return base

    def _get_wheel_nexus_path(self, path=None, goos=None, goarch=None):
        path = path or self._get_package_path()
        goos = goos or platform.system().lower()
        goarch = goarch or platform.machine().lower().replace("x86_64", "amd64")
        path = (path / f"bin-{goos}-{goarch}" / "wandb-nexus").resolve()
        return path

    def _build_nexus(self, path=None, goos=None, goarch=None, cgo_enabled=False):
        nexus_path = self._get_wheel_nexus_path(path=path, goos=goos, goarch=goarch)

        src_dir = Path(__file__).parent
        env = {}
        if goos:
            env["GOOS"] = goos
        if goarch:
            env["GOARCH"] = goarch
        # cgo is needed on:
        #  - arm macs to build the gopsutil dependency,
        #    otherwise several system metrics will be unavailable.
        #  - linux to build the dependencies needed to get GPU metrics.
        env["CGO_ENABLED"] = "1" if cgo_enabled else "0"
        os.makedirs(nexus_path.parent, exist_ok=True)

        # Sentry only allows 12 characters for release names, the full commit hash won't fit
        commit = (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=src_dir)
            .decode("utf-8")
            .strip()
        )

        # build linux binary with docker on mac
        if goos == "linux" and platform.system() != "Linux":
            # build docker image
            cmd = (
                "docker",
                "build",
                "-t",
                "wheel_builder",
                ".",
            )
            subprocess.check_call(
                cmd,
                cwd=src_dir / "scripts" / "build",
                env=dict(os.environ, **env),
            )

            # build wheels
            cmd = (
                "docker",
                "run",
                "--rm",
                "-v",
                f"{src_dir.parent}:/project",
                "-v",
                f"{src_dir.parent}/.cache/go-build:/root/.cache/go-build",
                "-e",
                f"COMMIT={commit}",
                "-e",
                f"NEXUS_PATH={str(nexus_path.relative_to(src_dir))}",
                "-e",
                "CGO_ENABLED=1",
                "wheel_builder",
            )
            log.info(f"Building wheel for {goos}-{goarch}")
            log.info(f"Running command: {' '.join(cmd)}")

            subprocess.check_call(
                cmd,
                cwd=src_dir.parent,
                env=dict(os.environ, **env),
            )
        else:
            ldflags = f"-s -w -X main.commit={commit}"
            cmd = (
                "go",
                "build",
                f"-ldflags={ldflags}",
                "-o",
                str(nexus_path),
                "cmd/nexus/main.go",
            )
            log.info(f"Building wheel for {goos}-{goarch}")
            log.info(f"Running command: {' '.join(cmd)}")
            subprocess.check_call(cmd, cwd=src_dir, env=dict(os.environ, **env))


class WrapInstall(install, NexusBase):
    def initialize_options(self):
        install.initialize_options(self)
        self.nexus_build = None

    def finalize_options(self):
        install.finalize_options(self)
        self.set_undefined_options("bdist_wheel", ("nexus_build", "nexus_build"))

    def run(self):
        install.run(self)

        nexus_wheel_path = self._get_wheel_nexus_path()
        if self.nexus_build is None and not nexus_wheel_path.exists():
            self._build_nexus()
            return

        if self.nexus_build == "all":
            for goos, goarch, cgo_enabled in ALL_PLATFORMS:
                self._build_nexus(goos=goos, goarch=goarch, cgo_enabled=cgo_enabled)

        else:
            for build in self.nexus_build.split(","):
                goos, goarch = build.split("-")
                # get the cgo_enabled flag from the ALL_PLATFORMS list
                cgo_enabled = [
                    x[2] for x in ALL_PLATFORMS if x[0] == goos and x[1] == goarch
                ][0]
                self._build_nexus(goos=goos, goarch=goarch, cgo_enabled=cgo_enabled)


class WrapDevelop(develop, NexusBase):
    def run(self):
        develop.run(self)
        self._build_nexus(path=Path("wandb_core"))


class WrapBdistWheel(bdist_wheel, NexusBase):
    user_options = [
        (
            "nexus-build=",
            None,
            "nexus binaries to build comma separated (e.g. darwin-arm64,linux-amd64)",
        ),
    ] + bdist_wheel.user_options

    def initialize_options(self):
        bdist_wheel.initialize_options(self)
        self.nexus_build = "all"

    def finalize_options(self):
        bdist_wheel.finalize_options(self)

    def run(self):
        bdist_wheel.run(self)


setup(
    name="wandb-core" if not _is_wandb_core_alpha else "wandb-core-alpha",
    version="0.0.1a3",
    description="Wandb core",
    packages=[PACKAGE],
    zip_safe=False,
    include_package_data=True,
    license="MIT license",
    python_requires=">=3.6",
    cmdclass={
        "install": WrapInstall,
        "develop": WrapDevelop,
        "bdist_wheel": WrapBdistWheel,
    },
)
