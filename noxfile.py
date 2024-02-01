import os
import pathlib
import platform
from typing import List

import nox

CORE_VERSION = "0.17.0b8"


PACKAGE: str = "wandb_core"
PLATFORMS_TO_BUILD_WITH_CGO = (
    "darwin-arm64",
    "linux-amd64",
)


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


@nox.session(python=False, name="build-go")
def build_go(session: nox.Session) -> None:
    """Builds the wandb-core binary for the current platform."""
    env = os.environ.copy()

    goos = platform.system().lower()
    goarch = platform.machine().lower()
    if goarch == "x86_64":
        goarch = "amd64"
    elif goarch == "aarch64":
        goarch = "arm64"
    elif goarch == "armv7l":
        goarch = "armv6l"

    # Check the PLAT environment variable available in cibuildwheel
    cibw_plat = env.get("PLAT", "")

    # Custom logic for darwin-arm64 in cibuildwheel
    # (it's built on an x86_64 mac with qemu, so we need to override the arch)
    if goos == "darwin" and cibw_plat.endswith("arm64"):
        goarch = "arm64"

    # build a binary for coverage profiling if the GOCOVERDIR env var is set
    gocover = True if os.environ.get("GOCOVERDIR") else False

    # cgo is needed on:
    #  - arm macs to build the gopsutil dependency,
    #    otherwise several system metrics will be unavailable.
    #  - linux to build the dependencies needed to get GPU metrics.
    if f"{goos}-{goarch}" in PLATFORMS_TO_BUILD_WITH_CGO:
        env["CGO_ENABLED"] = "1"

    commit = session.run(
        "git",
        "rev-parse",
        "HEAD",
        external=True,
        silent=True,
    ).strip()

    session.log(f"Commit: {commit}")

    # build the wandb-core binary in ./core:
    with session.chdir("core"):
        src_dir = pathlib.Path.cwd()
        out_dir = src_dir.parent / "client" / "wandb_core"

        ldflags = f"-s -w -X main.commit={commit}"
        if f"{goos}-{goarch}" == "linux-amd64":
            # TODO: try llvm's lld linker
            ldflags += ' -extldflags "-fuse-ld=gold -Wl,--weak-unresolved-symbols"'
        cmd = [
            "go",
            "build",
            f"-ldflags={ldflags}",
            "-o",
            str(out_dir / "wandb-core"),
            "cmd/wandb-core/main.go",
        ]
        if gocover:
            cmd.insert(2, "-cover")

        session.log(f"Building for {goos}-{goarch}")
        session.log(f"Running command: {' '.join(cmd)}")
        session.run(*cmd, env=env, external=True)

        # on arm macs, copy over the stats monitor binary, if available
        # it is built separately with `nox -s build-apple-stats-monitor` to avoid
        # having to wait for that to build on every run.
        if goos == "darwin" and goarch == "arm64":
            monitor_path = src_dir / "pkg/monitor/apple/AppleStats"
            if monitor_path.exists():
                session.log("Copying AppleStats binary")
                session.run(
                    "cp",
                    str(monitor_path),
                    str(out_dir),
                    external=True,
                )


@nox.session(python=False, name="build-rust")
def build_rust(session: nox.Session) -> None:
    """Builds the wandb-core wheel with maturin."""
    with session.chdir("client"):
        session.run(
            "maturin",
            "build",
            "--release",
            "--strip",
            external=True,
        )


@nox.session(python=False, name="install")
def install(session: nox.Session) -> None:
    # find latest wheel file in ./target/wheels/:
    wheel_file = [
        f
        for f in os.listdir("./client/target/wheels/")
        if f.startswith(f"wandb_core-{CORE_VERSION}") and f.endswith(".whl")
    ][0]
    session.run(
        "pip",
        "install",
        "--force-reinstall",
        f"./client/target/wheels/{wheel_file}",
        external=True,
    )


@nox.session(python=False, name="develop")
def develop(session: nox.Session) -> None:
    with session.chdir("client"):
        session.run(
            "maturin",
            "develop",
            "--release",
            "--strip",
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
            session.log("\n\nFailing tests grouped by feature:")
            df = pd.DataFrame(self.features)
            for feature, group in df.groupby("feature"):
                session.log(f"\n{feature}:")
                for name in group["name"]:
                    session.log(f"  {name}")

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
    with session.chdir("core/pkg/monitor/apple"):
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
    session.log(f"Release tag: {release_tag}")
    session.log(f"Commit hash: {commit_hash}")

    if not release_tag or not commit_hash:
        session.error("Failed to get release tag or commit hash.")

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
        session.warn(f"Image with tag {release_tag} already exists.")
        return

    source_image = f"us-central1-docker.pkg.dev/wandb-production/images/local-testcontainer:{commit_hash}"
    target_image = f"us-central1-docker.pkg.dev/wandb-client-cicd/images/local-testcontainer:{release_tag}"

    # install gcrane: `go install github.com/google/go-containerregistry/cmd/gcrane@latest`
    subprocess.check_call(["gcrane", "cp", source_image, target_image])

    session.log(f"Successfully copied image {target_image}")


@nox.session(python=False, name="bump-core-version")
def bump_core_version(session: nox.Session) -> None:
    args = session.posargs
    if not args:
        session.log("Usage: nox -s bump-core-version -- <args>\n")
        # Examples:
        session.log(
            "For example, to bump from 0.17.0b8/0.17.0-beta.8 to 0.17.0b9/0.17.0-beta.9:"
        )
        session.log("nox -s bump-core-version -- pre")
        return

    for cfg in (".bumpversion.core.cfg", ".bumpversion.cargo.cfg"):
        session.run(
            "bump2version",
            "--config-file",
            cfg,
            *args,
        )


@nox.session(python=False, name="proto-go")
def proto_go(session: nox.Session) -> None:
    session.run("./core/scripts/generate-proto.sh")
