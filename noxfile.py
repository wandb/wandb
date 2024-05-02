import os
import pathlib
import shutil
import time
from contextlib import contextmanager
from typing import Callable, Iterator, List

import nox

nox.options.default_venv_backend = "uv"

_SUPPORTED_PYTHONS = ["3.7", "3.8", "3.9", "3.10", "3.11", "3.12"]


@contextmanager
def report_time(session: nox.Session):
    t = time.time()
    yield
    session.log(f"Took {time.time() - t:.2f} seconds.")


def install_timed(session: nox.Session, *args, **kwargs):
    with report_time(session):
        session.install(*args, **kwargs)


def install_wandb(session: nox.Session):
    if session.venv_backend == "uv":
        install_timed(session, "--reinstall", "--refresh-package", "wandb", ".")
    else:
        install_timed(session, "--force-reinstall", ".")


def run_go_covtool(
    session: nox.Session,
    input: pathlib.Path,
    output: pathlib.Path,
) -> None:
    session.run(
        "go",
        "tool",
        "covdata",
        "textfmt",
        f"-i={input}",
        f"-o={output}",
        external=True,
    )


@contextmanager
def go_code_coverage(session: nox.Session) -> Iterator[str]:
    """Runs a command while collecting Go code coverage.

    This provides a gocoverdir path that should be passed as the
    GOCOVERDIR environment variable to the command.
    """
    # Using an absolute path is critical. We can't assume that the working
    # directory of the wandb-core binary will match the working directory
    # of the Nox session!
    gocoverdir = pathlib.Path(session.create_tmp(), "gocoverage").absolute()
    if gocoverdir.exists():
        shutil.rmtree(gocoverdir)
    gocoverdir.mkdir()

    yield str(gocoverdir)

    run_go_covtool(session, gocoverdir, pathlib.Path("coverage.txt"))


def run_pytest(
    session: nox.Session,
    gocoverdir: str,
    require_core: bool,
    paths: List[str],
) -> None:
    pytest_opts = []
    pytest_env = {
        "GOCOVERDIR": gocoverdir,
        "WANDB__REQUIRE_CORE": str(require_core),
        "WANDB__NETWORK_BUFFER": "1000",
        "WANDB_ERROR_REPORTING": "false",
        "WANDB_CORE_ERROR_REPORTING": "false",
        "USERNAME": session.env.get("USERNAME"),
        "PATH": session.env.get("PATH"),
        "USERPROFILE": session.env.get("USERPROFILE"),
    }

    # When running with core, skip tests that we know fail with it.
    if require_core:
        pytest_opts.extend(["-m", "not wandb_core_failure"])

    # Print 20 slowest tests.
    pytest_opts.append("--durations=20")

    # Output test results for tooling.
    pytest_opts.append("--junitxml=test-results/junit.xml")

    # (pytest-timeout) Per-test timeout.
    pytest_opts.append("--timeout=300")

    # (pytest-xdist) Run tests in parallel.
    pytest_opts.append("-n=8")

    # (pytest-split) Run a subset of tests only (for external parallelism).
    # These environment variables come from CircleCI.
    circle_node_total = session.env.get("CIRCLE_NODE_TOTAL")
    circle_node_index = session.env.get("CIRCLE_NODE_INDEX")
    if circle_node_total and circle_node_index:
        pytest_opts.append(f"--splits={circle_node_total}")
        pytest_opts.append(f"--group={int(circle_node_index) + 1}")

    # (pytest-cov) Enable code coverage reporting.
    pytest_opts.extend(["--cov", "--cov-report=xml", "--no-cov-on-fail"])
    pytest_env["COVERAGE_FILE"] = ".coverage"

    session.run(
        "pytest",
        *pytest_opts,
        *paths,
        env=pytest_env,
        include_outer_env=False,
    )


@nox.session(python=_SUPPORTED_PYTHONS)
@nox.parametrize("core", [True, False])
def unit_tests(session: nox.Session, core: bool) -> None:
    """Runs Python unit tests.

    By default this runs all unit tests, but specific tests can be selected
    by passing them via positional arguments.
    """
    session.env["WANDB_BUILD_COVERAGE"] = "true"
    session.env["WANDB_BUILD_UNIVERSAL"] = "false"

    install_wandb(session)

    install_timed(
        session,
        "-r",
        "requirements_dev.txt",
        # For test_reports:
        ".[reports]",
        "polyfactory",
    )

    with go_code_coverage(session) as gocoverdir:
        run_pytest(
            session,
            gocoverdir=gocoverdir,
            require_core=core,
            paths=session.posargs or ["tests/pytest_tests/unit_tests"],
        )


@nox.session(python=_SUPPORTED_PYTHONS)
@nox.parametrize("core", [True, False])
def system_tests(session: nox.Session, core: bool) -> None:
    session.env["WANDB_BUILD_COVERAGE"] = "true"
    session.env["WANDB_BUILD_UNIVERSAL"] = "false"

    install_wandb(session)
    install_timed(
        session,
        "-r",
        "requirements_dev.txt",
        "annotated-types",  # for test_reports
    )

    with go_code_coverage(session) as gocoverdir:
        run_pytest(
            session,
            gocoverdir=gocoverdir,
            require_core=core,
            paths=(
                session.posargs
                or [
                    "tests/pytest_tests/system_tests",
                    "--ignore=tests/pytest_tests/system_tests/test_importers",
                    "--ignore=tests/pytest_tests/system_tests/test_notebooks",
                ]
            ),
        )


@nox.session(python=_SUPPORTED_PYTHONS)
@nox.parametrize("core", [True, False])
def notebook_tests(session: nox.Session, core: bool) -> None:
    session.env["WANDB_BUILD_COVERAGE"] = "true"
    session.env["WANDB_BUILD_UNIVERSAL"] = "false"

    install_wandb(session)
    install_timed(
        session,
        "-r",
        "requirements_dev.txt",
        "nbclient",
        "nbconvert",
        "nbformat",
        "ipykernel",
        "ipython",
    )

    session.run(
        "ipython",
        "kernel",
        "install",
        "--user",
        "--name=wandb_python",
        external=True,
    )

    with go_code_coverage(session) as gocoverdir:
        run_pytest(
            session,
            gocoverdir=gocoverdir,
            require_core=core,
            paths=(
                session.posargs
                or [
                    "tests/pytest_tests/system_tests/test_notebooks",
                ]
            ),
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
        if f.startswith("wandb_core-") and f.endswith(".whl")
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

    session.install("packaging")
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


@nox.session(name="codegen")
def codegen(session: nox.Session) -> None:
    session.install("ruff")
    session.install(".")

    args = session.posargs
    if not args:
        args = ["--generate"]
    session.run("python", "tools/generate-tool.py", *args)


@nox.session(name="mypy-report")
def mypy_report(session: nox.Session) -> None:
    """Type-check the code with mypy.

    This session will install the package and run mypy with the --install-types flag.
    If the report parameter is set to True, it will also generate an html report.
    """
    session.install(
        # https://github.com/python/mypy/issues/17166
        "mypy != 1.10.0",
        "pycobertura",
        "lxml",
        "pandas-stubs",
        "types-click",
        "types-openpyxl",
        "types-Pillow",
        "types-PyYAML",
        "types-Pygments",
        "types-protobuf",
        "types-pytz",
        "types-requests",
        "types-setuptools",
        "types-six",
        "types-tqdm",
    )

    path = "mypy-results"

    if not pathlib.Path(path).exists():
        session.run(
            "mkdir",
            path,
            external=True,
        )

    session.run(
        "mypy",
        "--install-types",
        "--non-interactive",
        "--show-error-codes",
        "-p",
        "wandb",
        "--html-report",
        path,
        "--cobertura-xml-report",
        path,
        "--lineprecision-report",
        path,
    )

    session.run(
        "pycobertura",
        "show",
        "--format",
        "text",
        f"{path}/cobertura.xml",
    )
