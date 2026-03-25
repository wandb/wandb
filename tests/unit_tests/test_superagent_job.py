import json
import os
import pytest

from wandb.superagent.bootstrap import bootstrap
from wandb.superagent.job import (
    JobSourceKind,
    job_source_kind,
    job_source_kind_from_spec,
)


@pytest.fixture
def sandbox_job_root(mocker, tmp_path):
    """Temp job artifact dir; patches ``JOB_ARTIFACT_DIR`` for bootstrap tests."""
    root = tmp_path / "job"
    root.mkdir()
    mocker.patch("wandb.superagent.bootstrap.JOB_ARTIFACT_DIR", str(root))
    return root


def test_job_source_kind_from_spec_valid():
    assert (
        job_source_kind_from_spec({"source_type": "artifact"}) == JobSourceKind.ARTIFACT
    )
    assert job_source_kind_from_spec({"source_type": "repo"}) == JobSourceKind.REPO
    assert job_source_kind_from_spec({"source_type": "image"}) == JobSourceKind.IMAGE


@pytest.mark.parametrize(
    "spec, exc, match",
    [
        ({}, ValueError, "missing source_type"),
        ({"source_type": 1}, TypeError, "must be a string"),
        ({"source_type": "container"}, ValueError, "unsupported source_type"),
    ],
)
def test_job_source_kind_from_spec_errors(spec, exc, match):
    with pytest.raises(exc, match=match):
        job_source_kind_from_spec(spec)


def test_job_source_kind_from_dir(tmp_path):
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "wandb-job.json").write_text(
        json.dumps({"source_type": "repo", "source": {}}), encoding="utf-8"
    )
    assert job_source_kind(job_dir) == JobSourceKind.REPO


def test_bootstrap_image_no_fetch(mocker, tmp_path, sandbox_job_root):
    (sandbox_job_root / "wandb-job.json").write_text(
        json.dumps({"source_type": "image", "source": {"image": "busybox:latest"}}),
        encoding="utf-8",
    )
    dl = mocker.patch("wandb.superagent.bootstrap.download_job_source_artifact")
    fetch = mocker.patch("wandb.superagent.bootstrap._fetch_git_repo")

    ws = tmp_path / "ws"
    out = bootstrap(str(ws))
    assert out == str(ws)
    dl.assert_not_called()
    fetch.assert_not_called()
    assert not ws.exists()


def test_bootstrap_artifact_calls_download(mocker, tmp_path, sandbox_job_root):
    (sandbox_job_root / "wandb-job.json").write_text(
        json.dumps(
            {
                "source_type": "artifact",
                "source": {"artifact": "wandb-artifact://_id/x"},
            }
        ),
        encoding="utf-8",
    )
    (sandbox_job_root / "requirements.frozen.txt").write_text("wandb\n", encoding="utf-8")
    ws = tmp_path / "ws"
    mock_dl = mocker.patch(
        "wandb.superagent.bootstrap.download_job_source_artifact",
        return_value=str(ws),
    )
    fetch = mocker.patch("wandb.superagent.bootstrap._fetch_git_repo")

    bootstrap(str(ws))

    mock_dl.assert_called_once()
    fetch.assert_not_called()
    kwargs = mock_dl.call_args.kwargs
    assert kwargs["job_dir"] == str(sandbox_job_root)
    assert kwargs["root"] == str(ws)
    assert os.path.isfile(os.path.join(ws, "requirements.frozen.txt"))


def test_bootstrap_repo_calls_fetch(mocker, tmp_path, sandbox_job_root):
    (sandbox_job_root / "wandb-job.json").write_text(
        json.dumps(
            {
                "source_type": "repo",
                "source": {
                    "git": {"remote": "https://example.com/repo.git", "commit": "abc"},
                },
            }
        ),
        encoding="utf-8",
    )
    (sandbox_job_root / "requirements.frozen.txt").write_text("x\n", encoding="utf-8")
    ws = tmp_path / "ws"
    fetch = mocker.patch("wandb.superagent.bootstrap._fetch_git_repo")
    mocker.patch("wandb.superagent.bootstrap.apply_patch")
    dl = mocker.patch("wandb.superagent.bootstrap.download_job_source_artifact")

    bootstrap(str(ws))

    dl.assert_not_called()
    fetch.assert_called_once_with(
        str(ws),
        "https://example.com/repo.git",
        "abc",
    )
    assert os.path.isfile(os.path.join(ws, "requirements.frozen.txt"))


def test_bootstrap_artifact_no_requirements_file(mocker, tmp_path, sandbox_job_root):
    (sandbox_job_root / "wandb-job.json").write_text(
        json.dumps(
            {
                "source_type": "artifact",
                "source": {"artifact": "wandb-artifact://_id/x"},
            }
        ),
        encoding="utf-8",
    )
    ws = tmp_path / "ws"
    mocker.patch(
        "wandb.superagent.bootstrap.download_job_source_artifact",
        return_value=str(ws),
    )

    bootstrap(str(ws))

    assert not os.path.isfile(os.path.join(ws, "requirements.frozen.txt"))
