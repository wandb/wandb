import os
import platform

import nox

NEXUS_VERSION = "0.17.0b2"


@nox.session(python=False, name="build-nexus")
def build_nexus(session):
    """Builds the nexus binary for the current platform."""
    session.run(
        "python",
        "-m",
        "build",
        "-w",  # only build the wheel
        "-n",  # disable building the project in an isolated virtual environment
        "-x",  # do not check that build dependencies are installed
        "./nexus",
        external=True,
    )


@nox.session(python=False, name="install-nexus")
def install_nexus(session):
    """Installs the nexus wheel into the current environment."""
    # get the wheel file in ./nexus/dist/:
    wheel_file = [
        f
        for f in os.listdir("./nexus/dist/")
        if f.startswith(f"wandb_core-{NEXUS_VERSION}") and f.endswith(".whl")
    ][0]
    session.run(
        "pip",
        "install",
        "--force-reinstall",
        f"./nexus/dist/{wheel_file}",
        external=True,
    )


@nox.session(python=False, name="list-failing-tests-nexus")
def list_failing_tests_nexus(session):
    """Lists the nexus failing tests grouped by feature."""
    import pandas as pd
    import pytest

    class MyPlugin:
        def __init__(self):
            self.collected = []
            self.features = []

        def pytest_collection_modifyitems(self, items):
            for item in items:
                marks = item.own_markers
                for mark in marks:
                    if mark.name == "nexus_failure":
                        self.collected.append(item.nodeid)
                        self.features.append(
                            {
                                "name": item.nodeid,
                                "feature": mark.kwargs.get("feature", "unspecified"),
                            }
                        )

        def pytest_collection_finish(self):
            print("\n\nFailing tests grouped by feature:")
            df = pd.DataFrame(self.features)
            for feature, group in df.groupby("feature"):
                print(f"\n{feature}:")
                for name in group["name"]:
                    print(f"  {name}")

    my_plugin = MyPlugin()
    pytest.main(
        [
            "-m",
            "nexus_failure",
            "tests/pytest_tests/system_tests/test_core",
            "--collect-only",
        ],
        plugins=[my_plugin],
    )


@nox.session(python=False, name="download-codecov")
def download_codecov(session):
    system = platform.system().lower()
    if system == "darwin":
        system = "macos"
    url = f"https://uploader.codecov.io/latest/{system}/codecov"
    if system == "windows":
        url += ".exe"
        local_file = "codecov.exe"
    else:
        local_file = "codecov"

    session.run(
        "curl",
        "-o",
        local_file,
        url,
        external=True,
    )

    session.run("chmod", "+x", local_file, external=True)


@nox.session(python=False, name="run-codecov")
def run_codecov(session):
    args = session.posargs or []

    system = platform.system().lower()
    if system == "linux":
        command = ["./codecov"]
    elif system == "darwin":
        arch = platform.machine().lower()
        if arch != "x86_64":
            session.run("softwareupdate", "--install-rosetta", "--agree-to-license")
            command = ["arch", "-x86_64", "./codecov"]
        else:
            command = ["./codecov"]
    elif system == "windows":
        command = ["codecov.exe"]
    else:
        raise OSError("Unsupported operating system")

    command.extend(args)

    session.run(*command, external=True)


@nox.session(python=False, name="codecov")
def codecov(session):
    session.notify("download-codecov")
    session.notify("run-codecov", posargs=session.posargs)


if __name__ == "__main__":
    download_codecov()
    run_codecov()
