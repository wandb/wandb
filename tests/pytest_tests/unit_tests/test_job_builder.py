import json

from wandb.sdk.internal.job_builder import JobBuilder
from wandb.sdk.internal.settings_static import SettingsStatic


def test_build_repo_job(runner):

    metadata = {
        "git": {"remote": "testtest", "commit": "testtestcommit"},
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
        artifact = job_builder.build()
        assert artifact is not None
        assert artifact.name == "job-testtest_blah_test.py"
        assert artifact.type == "job"
        assert artifact._manifest.entries["wandb-job.json"]
        assert artifact._manifest.entries["requirements.frozen.txt"]


def test_build_artifact_job(runner):
    metadata = {
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
        job_builder._logged_code_artifact = {"id": "testtest", "name": "artifact_name"}
        artifact = job_builder.build()
        assert artifact is not None
        assert artifact.name == "job-artifact_name"
        assert artifact.type == "job"
        assert artifact._manifest.entries["wandb-job.json"]
        assert artifact._manifest.entries["requirements.frozen.txt"]


def test_build_image_job(runner):
    metadata = {
        "codePath": "blah/test.py",
        "args": ["--test", "test"],
        "python": "3.7",
        "docker": "mydockerimage",
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
        assert artifact.name == "job-mydockerimage"
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
