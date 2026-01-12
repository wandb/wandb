from __future__ import annotations

import json
import os
from unittest.mock import MagicMock

from wandb.apis.public import Job
from wandb.sdk.internal.job_builder import JobBuilder


def test_configure_notebook_repo_job(mocker, tmp_path):
    new_fname = "test.py"
    mocker.patch(
        "wandb.apis.public.jobs.convert_jupyter_notebook_to_script",
        lambda fname, project_dir: new_fname,
    )
    mocker.patch(
        "wandb.apis.public.jobs._fetch_git_repo", lambda dst_dir, uri, version: version
    )

    job_source = {
        "git": {"remote": "x", "commit": "y"},
        "entrypoint": ["python3", new_fname],
    }

    job = {
        "source_type": "repo",
        "source": job_source,
        "input_types": {"wb_type": "typedDict", "params": {"type_map": {}}},
        "output_types": {"wb_type": "typedDict", "params": {"type_map": {}}},
    }

    def mock_download(root):
        with open(os.path.join(root, "wandb-job.json"), "w") as f:
            json.dump(job, f)
        with open(os.path.join(root, "requirements.frozen.txt"), "w") as f:
            f.write("wandb")

    mock_artifact = MagicMock()
    mock_artifact.download.side_effect = mock_download

    def mock_download_code(root):
        with open(os.path.join(root, "test.ipynb"), "w") as f:
            f.write("hello")

    mock_code_artifact = MagicMock()
    mock_code_artifact.download.side_effect = mock_download_code

    mocker.patch("wandb.sdk.artifacts.artifact.Artifact._from_id", mock_artifact)

    mock_api = MagicMock()
    mock_api._artifact.return_value = mock_artifact

    job = Job(mock_api, "test/test/test_name:latest", tmp_path)
    mock_launch_project = MagicMock()

    proj_path = tmp_path / "proj_path"
    proj_path.mkdir()
    mock_launch_project.project_dir = tmp_path / proj_path

    job.configure_launch_project(mock_launch_project)
    mock_launch_project.set_job_entry_point.assert_called_with(["python3", new_fname])
    assert job._entrypoint == ["python3", new_fname]


def test_configure_notebook_artifact_job(mocker, tmp_path):
    new_fname = "test.py"
    mocker.patch(
        "wandb.apis.public.jobs.convert_jupyter_notebook_to_script",
        lambda fname, project_dir: new_fname,
    )

    job_source = {
        "artifact": "wandb-artifact://_id/test",
        "entrypoint": ["python3", new_fname],
    }

    job = {
        "source_type": "artifact",
        "source": job_source,
        "input_types": {"wb_type": "typedDict", "params": {"type_map": {}}},
        "output_types": {"wb_type": "typedDict", "params": {"type_map": {}}},
    }

    def mock_download(root):
        with open(os.path.join(root, "wandb-job.json"), "w") as f:
            json.dump(job, f)
        with open(os.path.join(root, "requirements.frozen.txt"), "w") as f:
            f.write("wandb")

    mock_artifact = MagicMock()
    mock_artifact.download.side_effect = mock_download

    def mock_download_code(root):
        with open(os.path.join(root, "test.ipynb"), "w") as f:
            f.write("hello")

    mocker.patch("wandb.sdk.artifacts.artifact.Artifact._from_id", mock_artifact)

    mock_api = MagicMock()
    mock_api._artifact.return_value = mock_artifact

    job = Job(mock_api, "test/test/test_name:latest", tmp_path)
    mock_launch_project = MagicMock()

    proj_path = tmp_path / "proj_path"
    proj_path.mkdir()
    mock_launch_project.project_dir = tmp_path / proj_path

    job.configure_launch_project(mock_launch_project)
    mock_launch_project.set_job_entry_point.assert_called_with(["python3", new_fname])
    assert job._entrypoint == ["python3", new_fname]


def test_make_job_name(test_settings):
    builder = JobBuilder(settings=test_settings(), files_dir="")
    name = builder._make_job_name("testing*123")

    assert name == "job-testing_123"

    settings = test_settings({"job_name": "custom-name"})
    builder = JobBuilder(settings=settings, files_dir="")
    name = builder._make_job_name("testing*123")

    assert name == "custom-name"
