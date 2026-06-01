import subprocess

import pytest
import wandb


def run_git(cwd, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def init_git_repo(path) -> None:
    subprocess.run(["git", "init", path], check=True, stdout=subprocess.DEVNULL)
    run_git(path, "config", "user.name", "test")
    run_git(path, "config", "user.email", "test@test.com")


def init_bare_git_repo(path) -> None:
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch", "main", path],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def git_add(cwd, pathspec: str) -> None:
    run_git(cwd, "add", pathspec)


def git_branch(cwd, *args: str) -> str:
    return run_git(cwd, "branch", *args)


def git_checkout(cwd, *args: str) -> str:
    return run_git(cwd, "checkout", *args)


def git_commit(cwd, message: str) -> None:
    run_git(cwd, "commit", "-m", message)


def git_fetch(cwd, remote: str) -> None:
    run_git(cwd, "fetch", remote)


def git_merge_base(cwd, *refs: str) -> str:
    return run_git(cwd, "merge-base", *refs)


def git_push(cwd, *args: str) -> None:
    run_git(cwd, "push", *args)


def git_remote_add(cwd, name: str, url: str) -> None:
    run_git(cwd, "remote", "add", name, url)


def git_rev_parse(cwd, ref: str) -> str:
    return run_git(cwd, "rev-parse", ref)


@pytest.fixture
def setup_repo_with_remote(tmp_path):
    base_repo_path = tmp_path / "base_repo"
    remote_repo_path = tmp_path / "remote_repo"
    init_git_repo(base_repo_path)
    init_bare_git_repo(remote_repo_path)
    git_remote_add(base_repo_path, "origin", str(remote_repo_path))

    (base_repo_path / "init.txt").write_text("init")
    git_add(base_repo_path, "init.txt")
    git_commit(base_repo_path, "Initial commit")
    git_push(base_repo_path, "origin", "HEAD:main")

    yield base_repo_path, remote_repo_path


def test_create_git_diff(user, wandb_backend_spy, setup_repo_with_remote):
    """
    Test that the git diff file is created from
    the currently staged changes and the HEAD of the current branch.
    """
    base_repo, _ = setup_repo_with_remote
    base_repo_path = base_repo

    (base_repo_path / "file2.txt").write_text("Hello, world!")
    git_add(base_repo_path, "file2.txt")

    with wandb.init(
        settings=wandb.Settings(root_dir=str(base_repo_path)),
    ) as run:
        pass

    with wandb_backend_spy.freeze() as snapshot:
        assert "diff.patch" in snapshot.uploaded_files(run_id=run.id)


def test_create_git_diff_from_upstream(
    user,
    wandb_backend_spy,
    setup_repo_with_remote,
):
    """
    Test that the git diff file is created from
    the upstream branch directly tracked by the current branch.
    """
    base_repo, remote_repo = setup_repo_with_remote
    base_repo_path = base_repo

    # create new branch
    git_checkout(base_repo_path, "-b", "feature1", "--track", "origin/main")
    (base_repo_path / "file2.txt").write_text("Hello, world!")
    git_add(base_repo_path, "file2.txt")
    git_commit(base_repo_path, "Add file2.txt")
    git_push(base_repo_path, "origin", "feature1")

    remote_head = git_rev_parse(remote_repo, "HEAD")

    with wandb.init(
        settings=wandb.Settings(root_dir=str(base_repo_path)),
    ) as run:
        pass

    with wandb_backend_spy.freeze() as snapshot:
        assert f"diff_{remote_head}.patch" in snapshot.uploaded_files(run_id=run.id)


def test_create_git_diff__finds_most_recent_ancestor(
    user,
    wandb_backend_spy,
    setup_repo_with_remote,
):
    """
    Tests that the git diff file is created from
    the most recent ancestor of the all upstream branches.
    """
    base_repo, _ = setup_repo_with_remote
    base_repo_path = base_repo

    # create 3 branches with different commits
    for i in range(3):
        git_checkout(base_repo_path, "-b", f"feature{i}")
        (base_repo_path / f"feature{i}.txt").write_text(f"feature content {i}")
        git_add(base_repo_path, f"feature{i}.txt")
        git_commit(base_repo_path, f"Adding feature {i}")
        git_push(base_repo_path, "origin", f"feature{i}")
        git_branch(base_repo_path, "-u", f"origin/feature{i}")

    # create a new branch which based off of feature 1 branch
    # and make a commit to this branch
    git_checkout(base_repo_path, "-b", "feature4", "feature1")
    (base_repo_path / "feature4.txt").write_text("feature4 content")
    git_add(base_repo_path, "feature4.txt")
    git_commit(base_repo_path, "Adding feature4")

    with wandb.init(
        settings=wandb.Settings(
            root_dir=str(base_repo_path),
            disable_git_fork_point=False,
        ),
    ) as run:
        pass

    with wandb_backend_spy.freeze() as snapshot:
        base_branch_head = git_rev_parse(base_repo_path, "feature1")
        assert f"diff_{base_branch_head}.patch" in snapshot.uploaded_files(
            run_id=run.id
        )


def test_create_git_diff__upstream_with_fork_point_disabled(
    user,
    wandb_backend_spy,
    setup_repo_with_remote,
):
    """With a tracking branch and disable_git_fork_point=True,
    the diff is generated against the latest upstream commit
    rather than the merge-base fork point.
    """
    base_repo, _ = setup_repo_with_remote
    base_repo_path = base_repo

    # Create a feature branch tracking origin/main
    git_checkout(base_repo_path, "-b", "feature1", "--track", "origin/main")
    (base_repo_path / "feature.txt").write_text("feature content")
    git_add(base_repo_path, "feature.txt")
    git_commit(base_repo_path, "Feature commit")

    # Advance origin/main past the fork point by pushing from main
    git_checkout(base_repo_path, "main")
    (base_repo_path / "main_advance.txt").write_text("main advanced")
    git_add(base_repo_path, "main_advance.txt")
    git_commit(base_repo_path, "Advance main")
    git_push(base_repo_path, "origin", "main")

    # Switch back to feature branch and fetch so origin/main ref updates
    git_checkout(base_repo_path, "feature1")
    git_fetch(base_repo_path, "origin")

    # @{upstream} now points to the advanced main commit,
    upstream_commit = git_rev_parse(base_repo_path, "@{upstream}")
    fork_point = git_merge_base(base_repo_path, "HEAD", "@{upstream}")
    assert upstream_commit != fork_point, (
        "Test setup: upstream should differ from fork point"
    )

    with wandb.init(
        settings=wandb.Settings(
            root_dir=str(base_repo_path),
            disable_git_fork_point=True,
        ),
    ) as run:
        pass

    with wandb_backend_spy.freeze() as snapshot:
        uploaded = snapshot.uploaded_files(run_id=run.id)
        assert f"diff_{upstream_commit}.patch" in uploaded


def test_create_git_diff__detached_head_no_upstream_diff(
    user,
    wandb_backend_spy,
    setup_repo_with_remote,
):
    """Detached HEAD produces no upstream diff patch."""
    base_repo, _ = setup_repo_with_remote
    base_repo_path = base_repo

    head_sha = git_rev_parse(base_repo_path, "HEAD")
    git_checkout(base_repo_path, head_sha)

    with wandb.init(
        settings=wandb.Settings(
            root_dir=str(base_repo_path),
            disable_git_fork_point=False,
        ),
    ) as run:
        pass

    with wandb_backend_spy.freeze() as snapshot:
        uploaded = snapshot.uploaded_files(run_id=run.id)
        upstream_patches = {
            f for f in uploaded if f.startswith("diff_") and f.endswith(".patch")
        }
        assert not upstream_patches, (
            f"Expected no upstream diff patches, got {upstream_patches}"
        )


def test_create_git_diff__no_upstream_fork_point_disabled(
    user,
    wandb_backend_spy,
    setup_repo_with_remote,
):
    """Branch with no upstream and disable_git_fork_point=True produces no upstream diff."""
    base_repo, _ = setup_repo_with_remote
    base_repo_path = base_repo

    git_checkout(base_repo_path, "-b", "orphan-branch")
    (base_repo_path / "orphan.txt").write_text("orphan content")
    git_add(base_repo_path, "orphan.txt")
    git_commit(base_repo_path, "Orphan commit")

    with wandb.init(
        settings=wandb.Settings(
            root_dir=str(base_repo_path),
            disable_git_fork_point=True,
        ),
    ) as run:
        pass

    with wandb_backend_spy.freeze() as snapshot:
        uploaded = snapshot.uploaded_files(run_id=run.id)
        upstream_patches = {
            f for f in uploaded if f.startswith("diff_") and f.endswith(".patch")
        }
        assert not upstream_patches, (
            f"Expected no upstream diff patches, got {upstream_patches}"
        )


def test_create_git_diff__no_tracking_branches_in_repo(
    user,
    wandb_backend_spy,
    tmp_path,
):
    """Repo with no tracking branches anywhere produces no upstream diff."""
    repo_path = tmp_path / "no_tracking_repo"
    init_git_repo(repo_path)

    (repo_path / "init.txt").write_text("init")
    git_add(repo_path, "init.txt")
    git_commit(repo_path, "Initial commit")

    (repo_path / "file2.txt").write_text("new content")
    git_add(repo_path, "file2.txt")
    git_commit(repo_path, "Second commit")

    with wandb.init(
        settings=wandb.Settings(
            root_dir=str(repo_path),
            disable_git_fork_point=False,
        ),
    ) as run:
        pass

    with wandb_backend_spy.freeze() as snapshot:
        uploaded = snapshot.uploaded_files(run_id=run.id)
        upstream_patches = {
            f for f in uploaded if f.startswith("diff_") and f.endswith(".patch")
        }
        assert not upstream_patches, (
            f"Expected no upstream diff patches, got {upstream_patches}"
        )
