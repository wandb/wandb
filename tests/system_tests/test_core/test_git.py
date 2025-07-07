import pathlib

import git
import pytest
import wandb


@pytest.fixture
def setup_repo_with_remote(tmp_path):
    base_repo_path = tmp_path / "base_repo"
    remote_repo_path = tmp_path / "remote_repo"
    base_repo = git.Repo.init(base_repo_path)
    base_repo.config_writer().set_value("user", "name", "test").release()
    base_repo.config_writer().set_value("user", "email", "test@test.com").release()
    remote_repo = git.Repo.init(remote_repo_path, bare=True, initial_branch="main")
    remote_repo.config_writer().set_value("user", "name", "test").release()
    remote_repo.config_writer().set_value("user", "email", "test@test.com").release()
    base_repo.git.remote("add", "origin", str(remote_repo.git_dir))

    (base_repo_path / "init.txt").write_text("init")
    base_repo.git.add("init.txt")
    base_repo.git.commit(m="Initial commit")
    base_repo.git.push("origin", "HEAD:main")

    yield base_repo, remote_repo

    base_repo.close()
    remote_repo.close()


def test_create_git_diff(user, wandb_backend_spy, setup_repo_with_remote):
    """
    Test that the git diff file is created from
    the currently staged changes and the HEAD of the current branch.
    """
    base_repo, _ = setup_repo_with_remote
    base_repo_path = pathlib.Path(base_repo.working_dir)

    (base_repo_path / "file2.txt").write_text("Hello, world!")
    base_repo.git.add("file2.txt")

    with wandb.init(
        settings=wandb.Settings(root_dir=base_repo.working_dir),
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
    base_repo_path = pathlib.Path(base_repo.working_dir)

    # create new branch
    base_repo.git.checkout("-b", "feature1", "--track", "origin/main")
    (base_repo_path / "file2.txt").write_text("Hello, world!")
    base_repo.git.add("file2.txt")
    base_repo.git.commit(m="Add file2.txt")
    base_repo.git.push("origin", "feature1")

    remote_head = remote_repo.head.commit.hexsha

    with wandb.init(
        settings=wandb.Settings(root_dir=base_repo.working_dir),
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
    base_repo_path = pathlib.Path(base_repo.working_dir)

    # create 3 branches with different commits
    for i in range(3):
        base_repo.git.checkout("-b", f"feature{i}")
        (base_repo_path / f"feature{i}.txt").write_text(f"feature content {i}")
        base_repo.git.add(f"feature{i}.txt")
        base_repo.git.commit(m=f"Adding feature {i}")
        base_repo.git.push("origin", f"feature{i}")
        base_repo.git.branch("-u", f"origin/feature{i}")

    # create a new branch which based off of feature 1 branch
    # and make a commit to this branch
    base_repo.git.checkout("-b", "feature4", "feature1")
    (base_repo_path / "feature4.txt").write_text("feature4 content")
    base_repo.git.add("feature4.txt")
    base_repo.git.commit(m="Adding feature4")

    with wandb.init(
        settings=wandb.Settings(
            root_dir=base_repo.working_dir,
            disable_git_fork_point=False,
        ),
    ) as run:
        pass

    with wandb_backend_spy.freeze() as snapshot:
        base_branch_head = base_repo.git.rev_parse("feature1")
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
    base_repo_path = pathlib.Path(base_repo.working_dir)

    # Create a feature branch tracking origin/main
    base_repo.git.checkout("-b", "feature1", "--track", "origin/main")
    (base_repo_path / "feature.txt").write_text("feature content")
    base_repo.git.add("feature.txt")
    base_repo.git.commit(m="Feature commit")

    # Advance origin/main past the fork point by pushing from main
    base_repo.git.checkout("main")
    (base_repo_path / "main_advance.txt").write_text("main advanced")
    base_repo.git.add("main_advance.txt")
    base_repo.git.commit(m="Advance main")
    base_repo.git.push("origin", "main")

    # Switch back to feature branch and fetch so origin/main ref updates
    base_repo.git.checkout("feature1")
    base_repo.git.fetch("origin")

    # @{upstream} now points to the advanced main commit,
    upstream_commit = base_repo.git.rev_parse("@{upstream}")
    fork_point = base_repo.git.merge_base("HEAD", "@{upstream}")
    assert upstream_commit != fork_point, (
        "Test setup: upstream should differ from fork point"
    )

    with wandb.init(
        settings=wandb.Settings(
            root_dir=base_repo.working_dir,
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

    head_sha = base_repo.head.commit.hexsha
    base_repo.git.checkout(head_sha)

    with wandb.init(
        settings=wandb.Settings(
            root_dir=base_repo.working_dir,
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
    base_repo_path = pathlib.Path(base_repo.working_dir)

    base_repo.git.checkout("-b", "orphan-branch")
    (base_repo_path / "orphan.txt").write_text("orphan content")
    base_repo.git.add("orphan.txt")
    base_repo.git.commit(m="Orphan commit")

    with wandb.init(
        settings=wandb.Settings(
            root_dir=base_repo.working_dir,
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
    repo = git.Repo.init(repo_path)
    repo.config_writer().set_value("user", "name", "test").release()
    repo.config_writer().set_value("user", "email", "test@test.com").release()

    (repo_path / "init.txt").write_text("init")
    repo.git.add("init.txt")
    repo.git.commit(m="Initial commit")

    (repo_path / "file2.txt").write_text("new content")
    repo.git.add("file2.txt")
    repo.git.commit(m="Second commit")

    try:
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
    finally:
        repo.close()
