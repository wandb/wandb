import json
import os
import subprocess
import sys
import pytest

from wandb.sdk.launch.errors import LaunchError
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
    pip = mocker.patch("wandb.superagent.bootstrap.subprocess.run")

    ws = tmp_path / "ws"
    out = bootstrap(str(ws))
    assert out == str(ws)
    dl.assert_not_called()
    fetch.assert_not_called()
    pip.assert_not_called()
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
    pip = mocker.patch(
        "wandb.superagent.bootstrap.subprocess.run",
        return_value=subprocess.CompletedProcess((), 0),
    )

    bootstrap(str(ws))

    mock_dl.assert_called_once()
    fetch.assert_not_called()
    kwargs = mock_dl.call_args.kwargs
    assert kwargs["job_dir"] == str(sandbox_job_root)
    assert kwargs["root"] == str(ws)
    assert os.path.isfile(os.path.join(ws, "requirements.frozen.txt"))
    pip.assert_called_once()
    assert pip.call_args.kwargs["cwd"] == str(ws)
    assert pip.call_args.args[0] == [
        sys.executable,
        "-m",
        "pip",
        "install",
        "-r",
        "requirements.frozen.txt",
    ]


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
    pip = mocker.patch(
        "wandb.superagent.bootstrap.subprocess.run",
        return_value=subprocess.CompletedProcess((), 0),
    )

    bootstrap(str(ws))

    dl.assert_not_called()
    fetch.assert_called_once_with(
        str(ws),
        "https://example.com/repo.git",
        "abc",
    )
    assert os.path.isfile(os.path.join(ws, "requirements.frozen.txt"))
    pip.assert_called_once()
    assert pip.call_args.kwargs["cwd"] == str(ws)


def test_bootstrap_skip_install(mocker, tmp_path, sandbox_job_root):
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
    mocker.patch(
        "wandb.superagent.bootstrap.download_job_source_artifact",
        return_value=str(ws),
    )
    pip = mocker.patch("wandb.superagent.bootstrap.subprocess.run")

    bootstrap(str(ws), install_dependencies=False)

    pip.assert_not_called()


def test_bootstrap_artifact_no_requirements_skips_pip(mocker, tmp_path, sandbox_job_root):
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
    pip = mocker.patch("wandb.superagent.bootstrap.subprocess.run")

    bootstrap(str(ws))

    pip.assert_not_called()


def test_bootstrap_pip_failure(mocker, tmp_path, sandbox_job_root):
    (sandbox_job_root / "wandb-job.json").write_text(
        json.dumps(
            {
                "source_type": "artifact",
                "source": {"artifact": "wandb-artifact://_id/x"},
            }
        ),
        encoding="utf-8",
    )
    (sandbox_job_root / "requirements.frozen.txt").write_text("badpkg===\n", encoding="utf-8")
    ws = tmp_path / "ws"
    mocker.patch(
        "wandb.superagent.bootstrap.download_job_source_artifact",
        return_value=str(ws),
    )
    mocker.patch(
        "wandb.superagent.bootstrap.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, ["pip"], stderr="nope"),
    )

    with pytest.raises(LaunchError, match="pip install failed"):
        bootstrap(str(ws))


def test_rewrite_dev_wandb_pins(mocker, tmp_path):
    from wandb.superagent import bootstrap as bootstrap_mod

    req = tmp_path / "requirements.frozen.txt"
    req.write_text(
        "numpy==1.0\nwandb==0.25.2.dev1\nclick==8.0\n",
        encoding="utf-8",
    )
    mocker.patch.object(bootstrap_mod.wandb, "__version__", "0.25.1")
    bootstrap_mod._rewrite_dev_wandb_pins(str(req))
    text = req.read_text(encoding="utf-8")
    assert "wandb==0.25.1" in text
    assert "0.25.2.dev1" not in text
    assert "numpy==1.0" in text
