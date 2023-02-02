import json
import string
import random

from wandb.sdk.internal.job_builder import MAX_ARTIFACT_NAME_LENGTH, JobBuilder
from wandb.sdk.internal.settings_static import SettingsStatic


def str_of_length(n):
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))


def test_build_repo_job(runner):
    remote_name = str_of_length(129)
    metadata = {
        "git": {"remote": remote_name, "commit": "testtestcommit"},
        "codePath": "blah/test.py",
        "args": ["--test", "test"],
        "python": "3.7",
    }
    with runner.isolated_filesystem():
        with open("requirements.txt", "w") as f:
            f.write("numpy==1.19.0")
            f.write("wandb")
        with open("wandb-metadata.json", "w") as f:
            f.write(json.dumps(metadata))
        settings = SettingsStatic({"files_dir": "./"})
        job_builder = JobBuilder(settings)
        max_len_remote = MAX_ARTIFACT_NAME_LENGTH - len("job-") - len("_blah_test.py")
        truncated_name = remote_name[:max_len_remote]
        artifact = job_builder.build()
        assert artifact is not None
        assert artifact.name == f"job-{truncated_name}_blah_test.py"
        assert artifact.type == "job"
        assert artifact._manifest.entries["wandb-job.json"]
        assert artifact._manifest.entries["requirements.frozen.txt"]


def test_build_artifact_job(runner):
    metadata = {
        "codePath": "blah/test.py",
        "args": ["--test", "test"],
        "python": "3.7",
    }
    artifact_name = str_of_length(129)
    with runner.isolated_filesystem():
        with open("requirements.txt", "w") as f:
            f.write("numpy==1.19.0")
            f.write("wandb")
        with open("wandb-metadata.json", "w") as f:
            f.write(json.dumps(metadata))
        settings = SettingsStatic({"files_dir": "./"})
        job_builder = JobBuilder(settings)
        job_builder._logged_code_artifact = {
            "id": "testtest",
            "name": artifact_name,
        }
        max_name_len = MAX_ARTIFACT_NAME_LENGTH - len("job-")
        truncated_name = artifact_name[-max_name_len:]
        artifact = job_builder.build()
        assert artifact is not None
        assert artifact.name == f"job-{truncated_name}"
        assert artifact.type == "job"
        assert artifact._manifest.entries["wandb-job.json"]
        assert artifact._manifest.entries["requirements.frozen.txt"]


def test_build_image_job(runner):
    image_name = str_of_length(129)
    metadata = {
        "codePath": "blah/test.py",
        "args": ["--test", "test"],
        "python": "3.7",
        "docker": image_name,
    }
    with runner.isolated_filesystem():
        with open("requirements.txt", "w") as f:
            f.write("numpy==1.19.0")
            f.write("wandb")
        with open("wandb-metadata.json", "w") as f:
            f.write(json.dumps(metadata))
        settings = SettingsStatic({"files_dir": "./"})
        job_builder = JobBuilder(settings)
        artifact = job_builder.build()
        assert artifact is not None
        truncated_name = image_name[: MAX_ARTIFACT_NAME_LENGTH - len("job-")]
        assert artifact.name == truncated_name
        assert artifact.type == "job"
        assert artifact._manifest.entries["wandb-job.json"]
        assert artifact._manifest.entries["requirements.frozen.txt"]


def test_set_disabled():
    settings = SettingsStatic({"files_dir": "./"})
    job_builder = JobBuilder(settings)
    job_builder.disable = "testtest"
    assert job_builder.disable == "testtest"


def test_no_metadata_file():
    settings = SettingsStatic({"files_dir": "./"})
    job_builder = JobBuilder(settings)
    artifact = job_builder.build()
    assert artifact is None
