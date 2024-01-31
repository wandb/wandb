import os
import platform
from typing import List

import nox

CORE_VERSION = "0.17.0b8"


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


@nox.session(python=False, name="install-client")
def install_client(session: nox.Session) -> None:
    session.cd("client")
    session.run(
        "maturin",
        "develop",
        "--release",
        "--strip",
        external=True,
    )


@nox.session(python=False, name="develop")
def develop(session: nox.Session) -> None:
    """Developers! Developers! Developers!"""
    session.notify("build-core")
    session.notify("install-core")
    session.notify("install-client")


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
def build_apple_stats_monitor(session: nox.Session) -> None:
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
def graphql_codegen_schema_change(session: nox.Session) -> None:
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


@nox.session(python=False, name="local-testcontainer-registry")
def local_testcontainer_registry(session: nox.Session) -> None:
    """Ensure we collect and store the latest local-testcontainer in the registry.

    This will find the latest released version (tag) of wandb/core,
    find associated commit hash, and then pull the local-testcontainer
    image with the same commit hash from
    us-central1-docker.pkg.dev/wandb-production/images/local-testcontainer
    and push it to the SDK's registry with the release tag,
    if it doesn't already exist there.

    To run locally, you must have the following environment variables set:
    - GITHUB_ACCESS_TOKEN: a GitHub personal access token with the repo scope
    - GOOGLE_APPLICATION_CREDENTIALS: path to a service account key file
      or a JSON string containing the key file contents

    To run this for a specific release tag, use:
    nox -s local-testcontainer-registry -- <release_tag>
    """
    tags: List[str] = session.posargs or []

    import subprocess

    def query_github(payload: dict[str, str]) -> dict[str, str]:
        import json

        import requests

        headers = {
            "Authorization": f"bearer {os.environ['GITHUB_ACCESS_TOKEN']}",
            "Content-Type": "application/json",
        }

        url = "https://api.github.com/graphql"
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        data = response.json()

        return data

    def get_release_tag_and_commit_hash(tags: List[str]):
        if not tags:
            # Get the latest release tag and commit hash
            query = """
            {
            repository(owner: "wandb", name: "core") {
                latestRelease {
                tagName
                tagCommit {
                    oid
                }
                }
            }
            }
            """
            payload = {"query": query}

            data = query_github(payload)

            return (
                data["data"]["repository"]["latestRelease"]["tagName"],
                data["data"]["repository"]["latestRelease"]["tagCommit"]["oid"],
            )
        else:
            # Get the commit hash for the given release tag
            query = """
            query($owner: String!, $repo: String!, $tag: String!) {
            repository(owner: $owner, name: $repo) {
                ref(qualifiedName: $tag) {
                target {
                    oid
                }
                }
            }
            }
            """
            # TODO: allow passing multiple tags?
            variables = {"owner": "wandb", "repo": "core", "tag": tags[0]}
            payload = {"query": query, "variables": variables}

            data = query_github(payload)

            return tags[0], data["data"]["repository"]["ref"]["target"]["oid"]

    local_release_tag, commit_hash = get_release_tag_and_commit_hash(tags)

    release_tag = local_release_tag.removeprefix("local/v")
    print(f"Release tag: {release_tag}")
    print(f"Commit hash: {commit_hash}")

    if not release_tag or not commit_hash:
        print("Failed to get release tag or commit hash.")
        return

    subprocess.check_call(["gcloud", "config", "set", "project", "wandb-client-cicd"])

    # Check if image with tag already exists in the SDK's Artifact registry
    images = (
        subprocess.Popen(
            [
                "gcloud",
                "artifacts",
                "docker",
                "tags",
                "list",
                "us-central1-docker.pkg.dev/wandb-client-cicd/images/local-testcontainer",
            ],
            stdout=subprocess.PIPE,
        )
        .communicate()[0]
        .decode()
        .split("\n")
    )
    images = [img for img in images if img]

    if any(release_tag in img for img in images):
        print(f"Image with tag {release_tag} already exists.")
        return

    source_image = f"us-central1-docker.pkg.dev/wandb-production/images/local-testcontainer:{commit_hash}"
    target_image = f"us-central1-docker.pkg.dev/wandb-client-cicd/images/local-testcontainer:{release_tag}"

    # install gcrane: `go install github.com/google/go-containerregistry/cmd/gcrane@latest`
    subprocess.check_call(["gcrane", "cp", source_image, target_image])

    print(f"Successfully copied image {target_image}")


@nox.session(python=False, name="proto-go")
def proto_go(session: nox.Session) -> None:
    """Generate Go bindings for protobufs."""
    session.run("./core/scripts/generate-proto.sh")


@nox.session(name="proto-python")
@nox.parametrize("pb", [3, 4])
def proto_python(session: nox.Session, pb: int) -> None:
    """Generate Python bindings for protobufs.

    The pb argument is the major version of the protobuf package to use.

    Tested with Python 3.10 on a Mac with an M1 chip.
    Absolutely does not work with Python 3.7.
    """
    if pb == 3:
        session.install("protobuf~=3.20.3")
        session.install("mypy-protobuf~=3.3.0")
        session.install("grpcio~=1.48.0")
        session.install("grpcio-tools~=1.48.0")
    elif pb == 4:
        session.install("protobuf~=4.23.4")
        session.install("mypy-protobuf~=3.5.0")
        session.install("grpcio~=1.50.0")
        session.install("grpcio-tools~=1.50.0")
    else:
        session.error("Invalid protobuf version given. `pb` must be 3 or 4.")

    session.install("-r", "requirements_build.txt")
    session.install(".")

    session.chdir("wandb/proto")
    session.run("python", "wandb_internal_codegen.py")


def _ensure_no_diff(session: nox.Session, due_to_session: str, in_directory: str) -> None:
    """Fails if `generate_session` modifies `outdir`."""

    saved = session.create_tmp()
    session.run("cp", "-r", in_directory, saved)
    session.notify(due_to_session)
    session.run("diff", in_directory, saved)


@nox.session(name="proto-check")
def proto_check(session: nox.Session) -> None:
    """Regenerates protobuf files and ensures nothing changed."""

    for pb in [3, 4]:
        _ensure_no_diff(
            session,
            due_to_session=f"proto-python(pb={pb})",
            in_directory=f"wandb/proto/v{pb}",
        )

    _ensure_no_diff(
        session,
        due_to_session="proto-go",
        in_directory="core/pkg/service",
    )
