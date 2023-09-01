import platform

import nox

NEXUS_VERSION = "0.0.1a3"


@nox.session(python=False, name="build-nexus")
def build_nexus(session):
    """Builds the nexus binary for the current platform."""
    system = platform.system().lower()
    arch = "amd64" if platform.machine() == "x86_64" else platform.machine()
    session.run(
        "python",
        "-m",
        "build",
        "-w",
        "-n",
        "./nexus",
        f"-C--build-option=bdist_wheel --nexus-build={system}-{arch}",
        external=True,
    )


@nox.session(python=False, name="build-nexus-all")
def build_nexus_all(session):
    """Builds the nexus binary for all platforms."""
    session.run("python", "-m", "build", "-w", "-n", "./nexus", external=True)


@nox.session(python=False, name="install-nexus")
def install_nexus(session):
    """Installs the nexus wheel into the current environment."""
    session.run(
        "pip",
        "install",
        "--force-reinstall",
        f"./nexus/dist/wandb_core-{NEXUS_VERSION}-py3-none-any.whl",
        external=True,
    )
