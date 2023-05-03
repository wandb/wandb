from wandb.sdk.launch.github_reference import GitHubReference


def test_parse_bad() -> None:
    """Expected parse failures, None result."""
    ref = GitHubReference.parse("not a url")
    assert ref is None
    ref = GitHubReference.parse("http://github.com")  # Not HTTPS
    assert ref is None


def test_parse_ssh() -> None:
    """We should be able to parse and reconstruct an SSH reference."""
    case = "git@github.com:wandb/examples.git"
    ref = GitHubReference.parse(case)
    assert ref.host == "github.com"
    assert ref.organization == "wandb"
    assert ref.repo == "examples"
    assert ref.path is None
    assert ref.repo_ssh() == case


def test_parse_organization() -> None:
    """Should parse URLs that only have an organization."""
    cases = [
        "https://github.com/wandb",
        # Only half-heartedly parsing non-repo URLs for now - don't support reconstructing this
        "https://github.com/orgs/wandb/people",
    ]
    for case in cases:
        ref = GitHubReference.parse(case)
        assert ref.host == "github.com"
        assert ref.organization == "wandb"


def test_parse_enterprise() -> None:
    """Should support non-github.com hosts."""
    case = "https://github.foo.bar.com/wandb/examples"
    ref = GitHubReference.parse(case)
    assert ref.host == "github.foo.bar.com"
    assert ref.organization == "wandb"
    assert ref.repo == "examples"
    assert ref.url() == case


def test_parse_repo() -> None:
    """Should parse URLs that have an organization and a repo."""
    # This case is special because we don't want to reconstruct url with the .git extension
    case = "https://github.com/wandb/examples.git"
    ref = GitHubReference.parse(case)
    assert ref.host == "github.com"
    assert ref.organization == "wandb"
    assert ref.repo == "examples"

    cases = [
        "https://github.com/wandb/examples",
        "https://github.com/wandb/examples/pulls",
        "https://github.com/wandb/examples/tree/master/examples/launch/launch-quickstart",
        "https://github.com/wandb/examples/blob/master/examples/launch/launch-quickstart/README.md",
    ]
    for case in cases:
        ref = GitHubReference.parse(case)
        assert ref.host == "github.com"
        assert ref.organization == "wandb"
        assert ref.repo == "examples"
        assert ref.url() == case


def test_parse_tree() -> None:
    """Should parse a URL for viewing a dir."""
    case = "https://github.com/wandb/examples/tree/master/examples/launch/launch-quickstart"
    ref = GitHubReference.parse(case)
    assert ref.host == "github.com"
    assert ref.organization == "wandb"
    assert ref.repo == "examples"
    assert ref.view == "tree"
    assert ref.path == "master/examples/launch/launch-quickstart"
    assert ref.url() == case


def test_parse_blob() -> None:
    """Should parse a URL for viewing a file."""
    case = "https://github.com/wandb/examples/blob/master/examples/launch/launch-quickstart/README.md"
    ref = GitHubReference.parse(case)
    assert ref.host == "github.com"
    assert ref.organization == "wandb"
    assert ref.repo == "examples"
    assert ref.view == "blob"
    assert ref.path == "master/examples/launch/launch-quickstart/README.md"
    assert ref.url() == case


def test_parse_auth() -> None:
    """Should parse a URL that includes a username/password."""
    case = "https://username@github.com/wandb/examples/blob/commit/path/entry.py"
    ref = GitHubReference.parse(case)
    assert ref.username == "username"
    assert ref.password is None
    assert ref.host == "github.com"
    assert ref.organization == "wandb"
    assert ref.repo == "examples"
    assert ref.view == "blob"
    assert ref.path == "commit/path/entry.py"
    assert ref.url() == case

    case = "https://username:pword@github.com/wandb/examples/blob/commit/path/entry.py"
    ref = GitHubReference.parse(case)
    assert ref.username == "username"
    assert ref.password == "pword"
    assert ref.host == "github.com"
    assert ref.organization == "wandb"
    assert ref.repo == "examples"
    assert ref.view == "blob"
    assert ref.path == "commit/path/entry.py"
    assert ref.url() == case


def test_update_ref() -> None:
    """Test reference updating."""
    case = "https://github.com/jamie-rasmussen/launch-test-private/blob/main/haspyenv/today.py"
    ref = GitHubReference.parse(case)
    # Simulate parsing refinement after fetch
    ref.path = None
    ref.ref = "main"
    ref.directory = "haspyenv"
    ref.file = "today.py"

    ref.update_ref("jamie/testing-a-branch")
    assert ref.ref_type is None
    assert ref.ref == "jamie/testing-a-branch"
    expected = "https://github.com/jamie-rasmussen/launch-test-private/blob/jamie/testing-a-branch/haspyenv/today.py"
    assert ref.url() == expected
