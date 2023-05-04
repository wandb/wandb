import json
import os
from unittest.mock import MagicMock

from wandb.apis.public import Job


def test_configure_notebook_repo_job(mocker, tmp_path):
    mocker.patch(
        "wandb.apis.public.convert_jupyter_notebook_to_script",
        lambda fname, project_dir: "_session_history.py",
    )
    mocker.patch(
        "wandb.apis.public._fetch_git_repo", lambda dst_dir, uri, version: version
    )

    notebook_source = {
        "executable": "python3",
        "notebook_artifact": "wandb-artifact://_id/test",
    }
    job_source = {
        "git": {"remote": "x", "commit": "y"},
        "entrypoint": None,
        "notebook": notebook_source,
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
        with open(os.path.join(root, "_session_history.ipynb"), "w") as f:
            f.write("hello")

    mock_code_artifact = MagicMock()
    mock_code_artifact.download.side_effect = mock_download_code

    mocker.patch("wandb.apis.public.Artifact.from_id", mock_artifact)

    mock_api = MagicMock()
    mock_api.artifact.return_value = mock_artifact

    job = Job(mock_api, "test/test/test_name:latest", tmp_path)
    mock_launch_project = MagicMock()

    proj_path = tmp_path / "proj_path"
    proj_path.mkdir()
    mock_launch_project.project_dir = tmp_path / proj_path

    job.configure_launch_project(mock_launch_project)
    assert mock_launch_project.add_entry_point.called_with(
        ["python3", "_session_history.py"]
    )
    assert job._entrypoint == ["python3", "_session_history.py"]


def test_configure_notebook_artifact_job(mocker, tmp_path):
    mocker.patch(
        "wandb.apis.public.convert_jupyter_notebook_to_script",
        lambda fname, project_dir: "_session_history.py",
    )

    notebook_source = {
        "executable": "python3",
        "notebook_artifact": "wandb-artifact://_id/test",
    }
    job_source = {
        "artifact": "wandb-artifact://_id/test",
        "entrypoint": None,
        "notebook": notebook_source,
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
        with open(os.path.join(root, "_session_history.ipynb"), "w") as f:
            f.write("hello")

    mocker.patch("wandb.apis.public.Artifact.from_id", mock_artifact)

    mock_api = MagicMock()
    mock_api.artifact.return_value = mock_artifact

    job = Job(mock_api, "test/test/test_name:latest", tmp_path)
    mock_launch_project = MagicMock()

    proj_path = tmp_path / "proj_path"
    proj_path.mkdir()
    mock_launch_project.project_dir = tmp_path / proj_path

    job.configure_launch_project(mock_launch_project)
    assert mock_launch_project.add_entry_point.called_with(
        ["python3", "_session_history.py"]
    )
    assert job._entrypoint == ["python3", "_session_history.py"]
