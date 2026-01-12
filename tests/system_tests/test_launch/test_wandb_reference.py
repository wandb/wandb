from __future__ import annotations

from wandb.sdk.launch.wandb_reference import WandbReference


def test_parse_bad() -> None:
    ref = WandbReference.parse("not a url")
    assert ref is None


def test_parse_hostonly() -> None:
    test_cases = [
        "https://wandb.ai",
        "https://wandb.ai/",
    ]
    for test_case in test_cases:
        ref = WandbReference.parse(test_case)
        assert ref.host == "wandb.ai"
        assert ref.url_host() == "https://wandb.ai"


def test_parse_beta() -> None:
    test_cases = [
        "https://beta.wandb.ai",
        "https://beta.wandb.ai/settings",
    ]
    for test_case in test_cases:
        ref = WandbReference.parse(test_case)
        assert ref.host == "beta.wandb.ai"
        assert ref.entity is None


def test_parse_run() -> None:
    test_cases = [
        "https://wandb.ai/my-entity/my-project/runs/2aqbwbek",
        "https://wandb.ai/my-entity/my-project/runs/2aqbwbek?workspace=user-my-entity",
        "https://wandb.ai/my-entity/my-project/runs/2aqbwbek/logs?workspace=user-my-entity",
    ]
    for test_case in test_cases:
        ref = WandbReference.parse(test_case)
        assert ref.is_run()
        assert ref.host == "wandb.ai"
        assert ref.entity == "my-entity"
        assert ref.project == "my-project"
        assert ref.run_id == "2aqbwbek"


def test_parse_run_localhost() -> None:
    """This format can be seen when running old unit tests."""
    test_case = "http://localhost:42051/mock_server_entity/test/runs/12345678"
    ref = WandbReference.parse(test_case)
    assert ref.is_run()
    assert ref.host == "localhost:42051"
    assert ref.entity == "mock_server_entity"
    assert ref.project == "test"
    assert ref.run_id == "12345678"


def test_parse_run_bare() -> None:
    test_cases = [
        "/my-entity/my-project/runs/2aqbwbek",
        "/my-entity/my-project/runs/2aqbwbek?workspace=user-my-entity",
        "/my-entity/my-project/runs/2aqbwbek/logs?workspace=user-my-entity",
    ]
    for test_case in test_cases:
        ref = WandbReference.parse(test_case)
        assert ref.is_bare()
        assert ref.is_run()
        assert ref.host is None
        assert ref.entity == "my-entity"
        assert ref.project == "my-project"
        assert ref.run_id == "2aqbwbek"


def test_parse_job() -> None:
    test_cases = [
        "https://wandb.ai/my-entity/my-project/artifacts/job/my-job.py",
        "https://wandb.ai/my-entity/my-project/artifacts/job/my-job.py/_view/versions",
        "https://wandb.ai/my-entity/my-project/artifacts/job/my-job.py/latest/lineage",
    ]
    for test_case in test_cases:
        ref = WandbReference.parse(test_case)
        assert ref.is_job()
        assert ref.host == "wandb.ai"
        assert ref.entity == "my-entity"
        assert ref.project == "my-project"
        assert ref.job_name == "my-job.py"
        assert ref.job_alias == "latest"
        assert ref.job_reference() == "my-job.py:latest"
        assert ref.job_reference_scoped() == "my-entity/my-project/my-job.py:latest"
    test_cases = [
        "https://wandb.ai/my-entity/my-project/artifacts/job/my-job.py/v0",
        "https://wandb.ai/my-entity/my-project/artifacts/job/my-job.py/v0/",
        "https://wandb.ai/my-entity/my-project/artifacts/job/my-job.py/v0/files",
    ]
    for test_case in test_cases:
        ref = WandbReference.parse(test_case)
        assert ref.is_job()
        assert ref.host == "wandb.ai"
        assert ref.entity == "my-entity"
        assert ref.project == "my-project"
        assert ref.job_name == "my-job.py"
        assert ref.job_alias == "v0"
        assert ref.job_reference() == "my-job.py:v0"
        assert ref.job_reference_scoped() == "my-entity/my-project/my-job.py:v0"


def test_parse_job_bare() -> None:
    test_cases = [
        "/my-entity/my-project/artifacts/job/my-job.py",
        "/my-entity/my-project/artifacts/job/my-job.py/_view/versions",
        "/my-entity/my-project/artifacts/job/my-job.py/latest/lineage",
    ]
    for test_case in test_cases:
        ref = WandbReference.parse(test_case)
        assert ref.is_bare()
        assert ref.is_job()
        assert ref.host is None
        assert ref.entity == "my-entity"
        assert ref.project == "my-project"
        assert ref.job_name == "my-job.py"
        assert ref.job_alias == "latest"
    test_cases = [
        "/my-entity/my-project/artifacts/job/my-job.py/v0",
        "/my-entity/my-project/artifacts/job/my-job.py/v0/",
        "/my-entity/my-project/artifacts/job/my-job.py/v0/files",
    ]
    for test_case in test_cases:
        ref = WandbReference.parse(test_case)
        assert ref.is_bare()
        assert ref.is_job()
        assert ref.host is None
        assert ref.entity == "my-entity"
        assert ref.project == "my-project"
        assert ref.job_name == "my-job.py"
        assert ref.job_alias == "v0"


def test_is_uri_job_or_run() -> None:
    test_cases = [
        "https://wandb.ai/my-entity/my-project/runs/2aqbwbek?workspace=user-my-entity",
        "/my-entity/my-project/runs/2aqbwbek",
        "/my-entity/my-project/artifacts/job/my-job.py/_view/versions",
        "https://wandb.ai/my-entity/my-project/artifacts/job/my-job.py/latest/lineage",
    ]
    for test_case in test_cases:
        assert WandbReference.is_uri_job_or_run(test_case)
    test_cases = [
        "",
        "https://wandb.ai/",
        "https://beta.wandb.ai/settings",
        "https://github.com/wandb/examples/pull/123/files",
    ]
    for test_case in test_cases:
        assert not WandbReference.is_uri_job_or_run(test_case)
