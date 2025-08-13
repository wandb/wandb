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


def test_creat_git_diff__finds_most_recent_ancestor(
    user,
    wandb_backend_spy,
    setup_repo_with_remote,
):
    """
    Tests that the git diff files is created from
    the most recent ancestor of the all upstream branches.
    """
    base_repo, _ = setup_repo_with_remote
    base_repo_path = pathlib.Path(base_repo.working_dir)

    # create 3 branches with different commits
    for i in range(3):
        base_repo.git.checkout("-b", f"feature{i}")
        (base_repo_path / f"feature{i}.txt").write_text(f"feature contest {i}")
        base_repo.git.add(f"feature{i}.txt")
        base_repo.git.commit(m=f"Adding feature {i}")
        base_repo.git.push("origin", f"feature{i}")
        base_repo.git.branch("-u", f"origin/feature{i}")

    # create a new branch which base if off of feature 1 branch
    # and make a commit to this branch
    base_repo.git.checkout("-b", "feature4", "feature1")
    (base_repo_path / "feature4.txt").write_text("feature4 content")
    base_repo.git.add("feature4.txt")
    base_repo.git.commit(m="Adding feature4")

    with wandb.init(
        settings=wandb.Settings(
            root_dir=base_repo.working_dir,
        ),
    ) as run:
        pass

    with wandb_backend_spy.freeze() as snapshot:
        base_branch_head = base_repo.git.rev_parse("feature1")
        assert f"diff_{base_branch_head}.patch" in snapshot.uploaded_files(
            run_id=run.id
        )
