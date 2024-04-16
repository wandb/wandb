import os
from typing import Callable, List

import nox

CORE_VERSION = "0.17.0b12.dev1"


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


@nox.session(python=False, name="proto-go", tags=["proto"])
def proto_go(session: nox.Session) -> None:
    """Generate Go bindings for protobufs."""
    _generate_proto_go(session)


def _generate_proto_go(session: nox.Session) -> None:
    session.run("./core/scripts/generate-proto.sh", external=True)


@nox.session(name="proto-python", tags=["proto"])
@nox.parametrize("pb", [3, 4])
def proto_python(session: nox.Session, pb: int) -> None:
    """Generate Python bindings for protobufs.

    The pb argument is the major version of the protobuf package to use.

    Tested with Python 3.10 on a Mac with an M1 chip.
    Absolutely does not work with Python 3.7.
    """
    _generate_proto_python(session, pb=pb)


def _generate_proto_python(session: nox.Session, pb: int) -> None:
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

    with session.chdir("wandb/proto"):
        session.run("python", "wandb_internal_codegen.py")


def _ensure_no_diff(
    session: nox.Session,
    after: Callable[[], None],
    in_directory: str,
) -> None:
    """Fails if the callable modifies the directory."""
    saved = session.create_tmp()
    session.run("cp", "-r", in_directory, saved, external=True)
    after()
    session.run("diff", in_directory, saved, external=True)
    session.run("rm", "-rf", saved, external=True)


@nox.session(name="proto-check-python", tags=["proto-check"])
@nox.parametrize("pb", [3, 4])
def proto_check_python(session: nox.Session, pb: int) -> None:
    """Regenerates Python protobuf files and ensures nothing changed."""
    _ensure_no_diff(
        session,
        after=lambda: _generate_proto_python(session, pb=pb),
        in_directory=f"wandb/proto/v{pb}/.",
    )


@nox.session(name="proto-check-go", tags=["proto-check"])
def proto_check_go(session: nox.Session) -> None:
    """Regenerates Go protobuf files and ensures nothing changed."""
    _ensure_no_diff(
        session,
        after=lambda: _generate_proto_go(session),
        in_directory="core/pkg/service/.",
    )
