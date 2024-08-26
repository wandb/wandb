import os
import pathlib
import platform
import re
import shutil
import time
from contextlib import contextmanager
from typing import Callable, Dict, List, Optional, Tuple

import nox

nox.options.default_venv_backend = "uv"

_SUPPORTED_PYTHONS = ["3.7", "3.8", "3.9", "3.10", "3.11", "3.12"]

# Directories in which to create temporary per-session directories
# containing test results and pytest/Go coverage.
#
# This is created by test sessions and then consumed + deleted by
# the 'coverage' session.
_NOX_PYTEST_COVERAGE_DIR = pathlib.Path(".nox-wandb", "pytest-coverage")
_NOX_PYTEST_RESULTS_DIR = pathlib.Path(".nox-wandb", "pytest-results")
_NOX_GO_COVERAGE_DIR = pathlib.Path(".nox-wandb", "go-coverage")


@contextmanager
def report_time(session: nox.Session):
    t = time.time()
    yield
    session.log(f"Took {time.time() - t:.2f} seconds.")


def install_timed(session: nox.Session, *args, **kwargs):
    with report_time(session):
        session.install(*args, **kwargs)


def install_wandb(session: nox.Session):
    """Builds and installs wandb."""
    session.env["WANDB_BUILD_COVERAGE"] = "true"
    session.env["WANDB_BUILD_GORACEDETECT"] = "true"
    session.env["WANDB_BUILD_UNIVERSAL"] = "false"

    if session.venv_backend == "uv":
        install_timed(session, "--reinstall", "--refresh-package", "wandb", ".")
    else:
        install_timed(session, "--force-reinstall", ".")


def get_session_file_name(session: nox.Session) -> str:
    """Returns the session name transformed to be usable in a file name."""
    return re.sub(r"[\(\)=\"\'\.]", "_", session.name)


def site_packages_dir(session: nox.Session) -> pathlib.Path:
    """Returns the site-packages directory of the current session's venv."""
    # https://stackoverflow.com/a/66191790/2640146
    if platform.system() == "Windows":
        return pathlib.Path(session.virtualenv.location, "Lib", "site-packages")
    else:
        return pathlib.Path(
            session.virtualenv.location,
            "lib",
            f"python{session.python}",
            "site-packages",
        )


def get_circleci_splits(session: nox.Session) -> Optional[Tuple[int, int]]:
    """Returns the test splitting arguments from our CircleCI config.

    When using test splitting, CircleCI sets the CIRCLE_NODE_TOTAL and
    CIRCLE_NODE_INDEX environment variables to indicate which group of
    tests we should run.

    This returns (index, total), with 0 <= index < total, if the variables
    are set. Otherwise, returns (0, 0).
    """
    circle_node_total = session.env.get("CIRCLE_NODE_TOTAL")
    circle_node_index = session.env.get("CIRCLE_NODE_INDEX")

    if circle_node_total and circle_node_index:
        return (int(circle_node_index), int(circle_node_total))

    return (0, 0)


def run_pytest(
    session: nox.Session,
    paths: List[str],
) -> None:
    session_file_name = get_session_file_name(session)

    pytest_opts = []
    pytest_env = {
        "USERNAME": session.env.get("USERNAME"),
        "PATH": session.env.get("PATH"),
        "USERPROFILE": session.env.get("USERPROFILE"),
        # Tool settings are often set here. We invoke Docker in system tests,
        # which uses auth information from the home directory.
        "HOME": session.env.get("HOME"),
        "CI": session.env.get("CI"),
        # Required for the importers tests
        "WANDB_TEST_SERVER_URL2": session.env.get("WANDB_TEST_SERVER_URL2"),
    }

    # Print 20 slowest tests.
    pytest_opts.append("--durations=20")

    # Output test results for tooling.
    junitxml = _NOX_PYTEST_RESULTS_DIR / session_file_name / "junit.xml"
    pytest_opts.append(f"--junitxml={junitxml}")
    session.notify("combine_test_results")

    # (pytest-timeout) Per-test timeout.
    pytest_opts.append("--timeout=300")

    # (pytest-xdist) Run tests in parallel.
    pytest_opts.append("-n=auto")

    # (pytest-split) Run a subset of tests only (for external parallelism).
    (circle_node_index, circle_node_total) = get_circleci_splits(session)
    if circle_node_total > 0:
        pytest_opts.append(f"--splits={circle_node_total}")
        pytest_opts.append(f"--group={int(circle_node_index) + 1}")

    # (pytest-cov) Enable Python code coverage collection.
    # We set "--cov-report=" to suppress terminal output.
    pytest_opts.extend(["--cov-report=", "--cov", "--no-cov-on-fail"])

    pytest_env.update(python_coverage_env(session))
    pytest_env.update(go_coverage_env(session))
    session.notify("coverage")

    session.run(
        "pytest",
        *pytest_opts,
        *paths,
        env=pytest_env,
        include_outer_env=False,
    )


def run_yea(
    session: nox.Session,
    shard: str,
    require_core: bool,
    yeadoc: bool,
    paths: List[str],
) -> None:
    """Runs tests using yea-wandb.

    yea is a custom test runner that allows running scripts and asserting on
    their outputs and side effects.

    Args:
        session: The current nox session.
        shard: The "--shard" argument to pass to yea. Only tests that declare
            a matching shard run.
        require_core: Whether to require("core") for the test.
        yeadoc: Whether to pass the "--yeadoc" argument to yea to make it scan
            for docstring tests.
        paths: The test paths to run or ["--all"].
    """
    yea_opts = [
        "--strict",
        *["--shard", shard],
        "--mitm",
    ]

    if yeadoc:
        yea_opts.append("--yeadoc")

    yea_env = {
        "YEACOV_SOURCE": str(site_packages_dir(session) / "wandb"),
        "USERNAME": session.env.get("USERNAME"),
        "PATH": session.env.get("PATH"),
        "WANDB_API_KEY": session.env.get("WANDB_API_KEY"),
        "WANDB__REQUIRE_CORE": str(require_core),
        # Set the _network_buffer setting to 1000 to increase the likelihood
        # of triggering flow control logic.
        "WANDB__NETWORK_BUFFER": "1000",
        # Disable writing to Sentry.
        "WANDB_ERROR_REPORTING": "false",
        "WANDB_CORE_ERROR_REPORTING": "false",
    }

    # is the version constraint needed?
    install_timed(
        session,
        "yea-wandb==0.9.20",
        "pip",  # used by yea to install per-test dependencies
    )

    (circle_node_index, circle_node_total) = get_circleci_splits(session)
    if circle_node_total > 0:
        yea_opts.append(f"--splits={circle_node_total}")
        yea_opts.append(f"--group={int(circle_node_index) + 1}")

    # yea invokes Python 'coverage'
    yea_env.update(python_coverage_env(session))
    yea_env.update(go_coverage_env(session))
    session.notify("coverage")

    session.run(
        "yea",
        *yea_opts,
        "run",
        *paths,
        env=yea_env,
        include_outer_env=False,
    )

    # yea always puts test results into test-results/junit-yea.xml, so we
    # give the file a unique name after to avoid conflicts when other sessions
    # also invoke yea.
    os.rename(
        pathlib.Path("test-results", "junit-yea.xml"),
        pathlib.Path(
            "test-results",
            f"junit-yea-{get_session_file_name(session)}.xml",
        ),
    )


@nox.session(python=_SUPPORTED_PYTHONS)
def unit_tests(session: nox.Session) -> None:
    """Runs Python unit tests.

    By default this runs all unit tests, but specific tests can be selected
    by passing them via positional arguments.
    """
    install_wandb(session)

    install_timed(
        session,
        "-r",
        "requirements_dev.txt",
        # For test_reports:
        ".[reports]",
        "polyfactory",
    )

    run_pytest(
        session,
        paths=session.posargs or ["tests/pytest_tests/unit_tests"],
    )


@nox.session(python=_SUPPORTED_PYTHONS)
def system_tests(session: nox.Session) -> None:
    install_wandb(session)
    install_timed(
        session,
        "-r",
        "requirements_dev.txt",
        "annotated-types",  # for test_reports
    )

    run_pytest(
        session,
        paths=(
            session.posargs
            or [
                "tests/pytest_tests/system_tests",
                "--ignore=tests/pytest_tests/system_tests/test_importers",
                "--ignore=tests/pytest_tests/system_tests/test_notebooks",
                "--ignore=tests/pytest_tests/system_tests/test_functional",
            ]
        ),
    )


@nox.session(python=_SUPPORTED_PYTHONS)
def notebook_tests(session: nox.Session) -> None:
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

    run_pytest(
        session,
        paths=(
            session.posargs
            or [
                "tests/pytest_tests/system_tests/test_notebooks",
            ]
        ),
    )


@nox.session(python=_SUPPORTED_PYTHONS)
def functional_tests_pytest(session: nox.Session):
    """Runs functional tests using pytest."""
    install_wandb(session)
    install_timed(
        session,
        "-r",
        "requirements_dev.txt",
    )

    run_pytest(
        session,
        paths=(session.posargs or ["tests/pytest_tests/system_tests/test_functional"]),
    )


@nox.session(python=_SUPPORTED_PYTHONS)
@nox.parametrize("core", [False, True], ["no_wandb_core", "wandb_core"])
def functional_tests(session: nox.Session, core: bool) -> None:
    """Runs functional tests using yea.

    The yea shard must be specified using the YEA_SHARD environment variable.
    The test paths to run may be specified via positional arguments.
    """
    shard = session.env.get("YEA_SHARD")
    if not shard:
        session.error("No YEA_SHARD environment variable specified")

    session.log(f"Using YEA_SHARD={shard}")

    install_wandb(session)
    run_yea(
        session,
        shard=shard,
        require_core=core,
        yeadoc=True,
        paths=(
            session.posargs
            or [
                "tests/functional_tests",
                "tests/standalone_tests",
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


@nox.session(name="proto-python", tags=["proto"], python="3.10")
@nox.parametrize("pb", [3, 4, 5])
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
    elif pb == 5:
        session.install("protobuf~=5.27.0")
        session.install("mypy-protobuf~=3.6.0")
        session.install("grpcio~=1.64.1")
        session.install("grpcio-tools~=1.64.1")
    else:
        session.error("Invalid protobuf version given. `pb` must be 3, 4, or 5.")

    session.install("packaging")

    with session.chdir("wandb/proto"):
        session.run("python", "wandb_generate_proto.py")


@nox.session(name="generate-deprecated", tags=["proto"], python="3.10")
def generate_deprecated_class_definition(session: nox.Session) -> None:
    session.install("-e", ".")

    with session.chdir("wandb/proto"):
        session.run("python", "wandb_generate_deprecated.py")


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
        in_directory="core/pkg/service_go_proto/.",
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
        "types-jsonschema",
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


def python_coverage_env(session: nox.Session) -> Dict[str, str]:
    """Returns environment variables configuring Python coverage output.

    Configures the 'coverage' tool https://coverage.readthedocs.io/en/latest/
    to be usable with the "coverage" session.

    Both yea and pytest invoke coverage; for pytest it is via the pytest-cov
    package.
    """
    # https://coverage.readthedocs.io/en/latest/cmd.html#data-file
    _NOX_PYTEST_COVERAGE_DIR.mkdir(exist_ok=True, parents=True)
    pycovfile = _NOX_PYTEST_COVERAGE_DIR / (
        ".coverage-" + get_session_file_name(session)
    )

    # Always pass an absolute path; we cannot assume the working
    # directory of the process.
    return {"COVERAGE_FILE": str(pycovfile.absolute())}


def go_coverage_env(session: nox.Session) -> Dict[str, str]:
    """Returns environment variables configuring Go coverage output.

    Intended for use with the "coverage" session.
    """
    _NOX_GO_COVERAGE_DIR.mkdir(exist_ok=True, parents=True)
    gocovdir = _NOX_GO_COVERAGE_DIR / get_session_file_name(session)
    gocovdir.mkdir(exist_ok=True)

    # We must pass an absolute directory to GOCOVERDIR because we cannot
    # assume the working directory of the Go process!
    return {"GOCOVERDIR": str(gocovdir.absolute())}


@nox.session(default=False)
def coverage(session: nox.Session) -> None:
    """Combines coverage outputs from test sessions.

    This is invoked automatically by test sessions and should not be
    invoked manually.
    """
    install_timed(session, "coverage[toml]")

    ###########################################################
    # Python coverage will be in a "coverage.xml" file.
    ###########################################################

    # https://coverage.readthedocs.io/en/latest/cmd.html#combining-data-files-coverage-combine
    py_directories = list(_NOX_PYTEST_COVERAGE_DIR.iterdir())
    if len(py_directories) > 0:
        session.run("coverage", "combine", *py_directories)
        session.run("coverage", "xml")
    else:
        session.warn("No Python coverage found.")
    shutil.rmtree(_NOX_PYTEST_COVERAGE_DIR, ignore_errors=True)

    ###########################################################
    # Go coverage will be in a "coverage.txt" file.
    ###########################################################

    go_directories = list(str(p) for p in _NOX_GO_COVERAGE_DIR.iterdir())
    go_combined = pathlib.Path(session.create_tmp(), "go")
    shutil.rmtree(go_combined, ignore_errors=True)
    go_combined.mkdir()
    session.run(
        "go",
        "tool",
        "covdata",
        "merge",
        f"-i={','.join(go_directories)}",
        f"-o={go_combined}",
        external=True,
    )
    shutil.rmtree(_NOX_GO_COVERAGE_DIR, ignore_errors=True)

    # The output directory won't be created if there was no Go coverage
    # collected. This can happen if only a subset of tests was run that
    # didn't spin up wandb-core.
    if go_combined.exists():
        session.run(
            "go",
            "tool",
            "covdata",
            "textfmt",
            f"-i={go_combined}",
            "-o=coverage.txt",
            external=True,
        )


@nox.session(default=False)
def combine_test_results(session: nox.Session) -> None:
    """Merges Python test results into a test-results/junit.xml file.

    This is invoked automatically by test sessions and should not be
    invoked manually.
    """
    install_timed(session, "junitparser")

    pathlib.Path("test-results").mkdir(exist_ok=True)
    xml_paths = list(_NOX_PYTEST_RESULTS_DIR.glob("*/junit.xml"))
    session.run(
        "junitparser",
        "merge",
        *xml_paths,
        "test-results/junit.xml",
    )

    shutil.rmtree(_NOX_PYTEST_RESULTS_DIR, ignore_errors=True)


@nox.session(name="bump-go-version")
def bump_go_version(session: nox.Session) -> None:
    """Bump the Go version."""
    install_timed(session, "bump2version", "requests")

    # Get the latest Go version
    latest_version = session.run(
        "./tools/get_go_version.py",
        silent=True,
        external=True,
    )
    latest_version = latest_version.strip()

    session.log(f"Latest Go version: {latest_version}")

    # Run bump2version with the fetched version
    session.run(
        "bump2version",
        "patch",
        "--new-version",
        latest_version,
        "--config-file",
        ".bumpversion.go.cfg",
        "--no-commit",
        "--allow-dirty",
        external=True,
    )


@nox.session(python=_SUPPORTED_PYTHONS)
def launch_release_tests(session: nox.Session) -> None:
    """Run launch-release tests.

    See tests/release_tests/test_launch/README.md for more info.
    """
    install_wandb(session)
    install_timed(
        session,
        "pytest",
        "wandb[launch]",
    )

    session.run("wandb", "login")

    run_pytest(
        session,
        paths=session.posargs or ["tests/release_tests/test_launch/"],
    )


@nox.session(python=_SUPPORTED_PYTHONS)
@nox.parametrize("importer", ["wandb", "mlflow"])
def importer_tests(session: nox.Session, importer: str):
    """Run importer tests for wandb->wandb and mlflow->wandb."""
    install_wandb(session)
    session.install("-r", "requirements_dev.txt")
    if importer == "wandb":
        session.install(".[workspaces]", "pydantic>=2")
    elif importer == "mlflow":
        session.install("pydantic<2")
    if session.python != "3.7":
        session.install("polyfactory")
    session.install(
        "polars<=1.2.1",
        "rich",
        "filelock",
    )

    run_pytest(
        session,
        paths=(
            session.posargs
            or [f"tests/pytest_tests/system_tests/test_importers/test_{importer}"]
        ),
    )
