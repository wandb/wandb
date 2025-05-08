from __future__ import annotations

import os
import pathlib
import platform
import re
import shutil
import time
from contextlib import contextmanager
from typing import Any, Callable

import nox

nox.options.default_venv_backend = "uv"

_SUPPORTED_PYTHONS = ["3.8", "3.9", "3.10", "3.11", "3.12", "3.13"]

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


def get_circleci_splits() -> tuple[int, int]:
    """Returns the test splitting arguments from our CircleCI config.

    When using test splitting, CircleCI sets the CIRCLE_NODE_TOTAL and
    CIRCLE_NODE_INDEX environment variables to indicate which group of
    tests we should run.

    This returns (index, total), with 0 <= index < total, if the variables
    are set. Otherwise, returns (0, 0).
    """
    circle_node_total = os.environ.get("CIRCLE_NODE_TOTAL")
    circle_node_index = os.environ.get("CIRCLE_NODE_INDEX")

    if circle_node_total and circle_node_index:
        return (int(circle_node_index), int(circle_node_total))

    return (0, 0)


def run_pytest(
    session: nox.Session,
    paths: list[str],
    opts: dict[str, str] | None = None,
) -> None:
    session_file_name = get_session_file_name(session)

    opts = opts or {}
    pytest_opts = []
    pytest_env = {
        "PATH": session.env.get("PATH") or os.environ.get("PATH"),
        "USERNAME": os.environ.get("USERNAME"),
        "USERPROFILE": os.environ.get("USERPROFILE"),
        # Tool settings are often set here. We invoke Docker in system tests,
        # which uses auth information from the home directory.
        "HOME": os.environ.get("HOME"),
        "CI": os.environ.get("CI"),
        # Required for the importers tests
        "WANDB_TEST_SERVER_URL2": os.environ.get("WANDB_TEST_SERVER_URL2"),
        # Required for functional tests with openai
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
    }

    # Print 20 slowest tests.
    pytest_opts.append(f"--durations={opts.get('durations', 20)}")

    if platform.system() != "Windows":  # memray is not supported on Windows.
        # Track and report memory usage with memray.
        pytest_opts.append("--memray")
        # Show the 5 tests that allocate most memory.
        pytest_opts.append("--most-allocations=5")

    # Output test results for tooling.
    junitxml = _NOX_PYTEST_RESULTS_DIR / session_file_name / "junit.xml"
    pytest_opts.append(f"--junitxml={junitxml}")
    session.notify("combine_test_results")

    # (pytest-timeout) Per-test timeout.
    pytest_opts.append(f"--timeout={opts.get('timeout', 300)}")

    # (pytest-xdist) Run tests in parallel.
    pytest_opts.append(f"-n={opts.get('n', 'auto')}")

    # Limit the # of workers in CI. Due to heavy tensorflow and pytorch imports,
    # each worker uses up 700MB+ of memory, so with a large number of workers,
    # we start to max out the RAM and slow down. This also causes flakes in
    # time-dependent tests.
    pytest_opts.append("--maxprocesses=10")

    # (pytest-split) Run a subset of tests only (for external parallelism).
    (circle_node_index, circle_node_total) = get_circleci_splits()
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
        "polyfactory",
    )

    run_pytest(
        session,
        paths=session.posargs or ["tests/unit_tests"],
        # TODO: consider relaxing this once the test memory usage is under control.
        opts={"n": "8"},
    )


@nox.session(python=_SUPPORTED_PYTHONS)
def unit_tests_pydantic_v1(session: nox.Session) -> None:
    """Runs a subset of Python unit tests with pydantic v1."""
    install_wandb(session)
    install_timed(
        session,
        "-r",
        "requirements_test.txt",
    )
    # force-downgrade pydantic to v1
    install_timed(session, "pydantic<2")

    run_pytest(
        session,
        paths=session.posargs
        or [
            "tests/unit_tests/test_wandb_settings.py",
            "tests/unit_tests/test_wandb_metadata.py",
            "tests/unit_tests/test_wandb_run.py",
            "tests/unit_tests/test_pydantic_v1_compat.py",
        ],
        opts={"n": "4"},
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
                "tests/system_tests",
                "--ignore=tests/system_tests/test_importers",
                "--ignore=tests/system_tests/test_notebooks",
                "--ignore=tests/system_tests/test_functional",
                "--ignore=tests/system_tests/test_experimental",
            ]
        ),
        # TODO: consider relaxing this once the test memory usage is under control.
        opts={"n": "8"},
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
                "tests/system_tests/test_notebooks",
            ]
        ),
    )


@nox.session(python=_SUPPORTED_PYTHONS)
def functional_tests(session: nox.Session):
    """Runs functional tests using pytest."""
    install_wandb(session)
    install_timed(
        session,
        "-r",
        "requirements_dev.txt",
    )

    run_pytest(
        session,
        paths=(session.posargs or ["tests/system_tests/test_functional"]),
        # the default n=auto spins up too many workers on CircleCI as it's
        # based on the number of detected CPUs in the system, and doesn't
        # take into account the number of available CPUs in the container,
        # which results in OOM errors.
        opts={"n": "4"},
    )


@nox.session(python=_SUPPORTED_PYTHONS)
def experimental_tests(session: nox.Session):
    """Runs functional tests of experimental clients in different languages using pytest."""
    install_wandb(session)
    install_timed(
        session,
        "-r",
        "requirements_dev.txt",
    )

    run_pytest(
        session,
        paths=(session.posargs or ["tests/system_tests/test_experimental"]),
        # TODO: increase as more tests are added
        opts={"n": "1"},
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
    tags: list[str] = session.posargs or []

    import subprocess

    def query_github(payload: dict[str, Any]) -> dict[str, Any]:
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

    def get_release_tag_and_commit_hash(tags: list[str]):
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

            data = query_github({"query": query})

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

            data = query_github(
                {
                    "query": query,
                    "variables": {
                        "owner": "wandb",
                        "repo": "core",
                        "tag": tags[0],
                    },
                }
            )

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


@nox.session(python=False, name="proto-rust", tags=["proto"])
def proto_rust(session: nox.Session) -> None:
    """Generate Rust bindings for protobufs."""
    session.run("./core/api/proto/install-protoc.sh", "23.4", external=True)
    session.run("./gpu_stats/tools/generate-proto.sh", external=True)


@nox.session(python=False, name="proto-go", tags=["proto"])
def proto_go(session: nox.Session) -> None:
    """Generate Go bindings for protobufs."""
    _generate_proto_go(session)


def _generate_proto_go(session: nox.Session) -> None:
    session.run("./core/api/proto/generate-proto.sh", external=True)


@nox.session(name="proto-python", tags=["proto"], python="3.10")
@nox.parametrize("pb", [3, 4, 5, 6])
def proto_python(session: nox.Session, pb: int) -> None:
    """Generate Python bindings for protobufs.

    The pb argument is the major version of the protobuf package to use.

    Tested with Python 3.10 on a Mac with an M1 chip.
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
    elif pb == 6:
        session.install("mypy-protobuf==3.6.0")
        # TODO: update to 1.72.0 when released
        session.install("grpcio==1.72.0rc1")
        session.install("grpcio-tools==1.72.0rc1")
        session.install("protobuf==6.30.2")
    else:
        session.error("Invalid protobuf version given. `pb` must be 3, 4, 5, or 6.")

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
        "bokeh",
        "ipython",
        "lxml",
        # https://github.com/python/mypy/issues/17166
        "mypy != 1.10.0",
        "numpy",
        "pandas-stubs",
        "pip",
        "platformdirs",
        "pydantic",
        "pycobertura",
        "types-jsonschema",
        "types-openpyxl",
        "types-Pillow",
        "types-protobuf",
        "types-Pygments",
        "types-python-dateutil",
        "types-pytz",
        "types-PyYAML",
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


def python_coverage_env(session: nox.Session) -> dict[str, str]:
    """Returns environment variables configuring Python coverage output.

    Configures the 'coverage' tool https://coverage.readthedocs.io/en/latest/
    to be usable with the "coverage" session.

    pytest invoke coverage; for pytest it is via the pytest-cov package.
    """
    # https://coverage.readthedocs.io/en/latest/cmd.html#data-file
    _NOX_PYTEST_COVERAGE_DIR.mkdir(exist_ok=True, parents=True)
    pycovfile = _NOX_PYTEST_COVERAGE_DIR / (
        ".coverage-" + get_session_file_name(session)
    )

    # Always pass an absolute path; we cannot assume the working
    # directory of the process.
    return {"COVERAGE_FILE": str(pycovfile.absolute())}


def go_coverage_env(session: nox.Session) -> dict[str, str]:
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

    # Get the latest Go version.
    get_go_version_output = session.run(
        "./tools/get_go_version.py",
        silent=True,
        external=True,
    )

    # Guaranteed by silent=True above, but poorly documented in nox.
    assert isinstance(get_go_version_output, str)

    latest_version = get_go_version_output.strip()
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
@nox.parametrize("importer", ["wandb", "mlflow"])
def importer_tests(session: nox.Session, importer: str):
    """Run importer tests for wandb->wandb and mlflow->wandb."""
    install_wandb(session)
    session.install("-r", "requirements_dev.txt")
    if importer == "wandb":
        session.install(".[workspaces]", "pydantic>=2")
    elif importer == "mlflow":
        session.install("pydantic<2")
    session.install(
        "polyfactory",
        "polars<=1.2.1",
        "rich",
        "filelock",
    )

    run_pytest(
        session,
        paths=(
            session.posargs or [f"tests/system_tests/test_importers/test_{importer}"]
        ),
    )
