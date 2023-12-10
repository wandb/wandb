import os
import platform

import nox

CORE_VERSION = "0.17.0b3"


@nox.session(python=False, name="build-core")
def build_core(session: nox.Session) -> None:
    """Builds the wandb-core binary for the current platform."""
    session.run(
        "python3",
        "-m",
        "build",
        "-w",  # only build the wheel
        "-n",  # disable building the project in an isolated virtual environment
        "-x",  # do not check that build dependencies are installed
        "./core",
        external=True,
    )


@nox.session(python=False, name="install-core")
def install_core(session: nox.Session) -> None:
    """Installs the wandb-core wheel into the current environment."""
    # get the wheel file in ./core/dist/:
    wheel_file = [
        f
        for f in os.listdir("./core/dist/")
        if f.startswith(f"wandb_core-{CORE_VERSION}") and f.endswith(".whl")
    ][0]
    session.run(
        "pip",
        "install",
        "--force-reinstall",
        f"./core/dist/{wheel_file}",
        external=True,
    )


@nox.session(python=False, name="list-failing-tests-wandb-core")
def list_failing_tests_wandb_core(session: nox.Session) -> None:
    """Lists the core failing tests grouped by feature."""
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
                    if mark.name == "wandb_core_failure":
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
            "wandb_core_failure",
            "tests/pytest_tests/system_tests/test_core",
            "--collect-only",
        ],
        plugins=[my_plugin],
    )


@nox.session(python=False, name="download-codecov")
def download_codecov(session: nox.Session) -> None:
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
def run_codecov(session: nox.Session) -> None:
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
def codecov(session: nox.Session) -> None:
    session.notify("download-codecov")
    session.notify("run-codecov", posargs=session.posargs)


@nox.session(python=False, name="build-apple-stats-monitor")
def build_apple_stats_monitor(session):
    """Builds the apple stats monitor binary for the current platform.

    The binary will be located in
    core/pkg/monitor/apple/.build/<arch>-apple-macosx/release/AppleStats
    """
    session.cd("core/pkg/monitor/apple")
    session.run(
        "swift",
        "build",
        "--configuration",
        "release",
        "-Xswiftc",
        "-cross-module-optimization",
        external=True,
    )
    # copy the binary to core/pkg/monitor/apple/AppleStats
    session.run(
        "cp",
        f".build/{platform.machine().lower()}-apple-macosx/release/AppleStats",
        "AppleStats",
    )


@nox.session(python=False, name="graphql-codegen-schema-change")
def graphql_codegen_schema_change(session):
    """Runs the GraphQL codegen script and saves the previous api version.

    This will save the current generated go graphql code gql_gen.go
    in core/internal/gql/v[n+1]/gql_gen.go, run the graphql codegen script,
    and save the new generated go graphql code as core/internal/gql/gql_gen.go.
    The latter will always point to the latest api version, while the versioned
    gql_gen.go files can be used in versioning your GraphQL API requests,
    for example when communicating with an older server.

    Should use whenether there is a schema change on the Server side that
    affects your GraphQL API. Do not use this if there is no schema change
    and you are e.g. just adding a new query or mutation
    against the schema that already supports it.
    """
    session.run(
        "./core/scripts/generate-graphql.sh",
        "--schema-change",
        external=True,
    )
