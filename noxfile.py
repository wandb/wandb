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
        f"--config-setting=--build-option=--nexus-build={system}-{arch}",
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
