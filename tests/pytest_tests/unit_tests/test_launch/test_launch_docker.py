import os
from unittest.mock import MagicMock

from wandb.sdk.launch._project_spec import EntryPoint
from wandb.sdk.launch.builder.build import generate_dockerfile


def test_buildx_not_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "wandb.sdk.launch.builder.build.docker.is_buildx_installed", lambda: False
    )

    mock_project = MagicMock()
    mock_project.deps_type = "pip"
    mock_project.project_dir = tmp_path
    mock_project.override_entrypoint = None
    with open(os.path.join(tmp_path, "requirements.txt"), "w") as fp:
        fp.write("wandb")

    dockerfile = generate_dockerfile(
        mock_project, EntryPoint("main.py", ["python", "train.py"]), "local", "docker"
    )

    assert "RUN WANDB_DISABLE_CACHE=true" in dockerfile
