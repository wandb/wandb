from wandb.sdk.launch.wandb_reference import WandbReference


def test_parse_bad():
    ref = WandbReference.parse("not a url")
    assert ref is None
    ref = WandbReference.parse("http://wandb.ai")  # Not HTTPS
    assert ref is None


def test_parse_hostonly():
    cases = [
        "https://wandb.ai",
        "https://wandb.ai/",
    ]
    for case in cases:
        ref = WandbReference.parse(case)
        assert ref.host == "wandb.ai"
        assert ref.url_host() == "https://wandb.ai"


def test_parse_beta():
    cases = [
        "https://beta.wandb.ai",
        "https://beta.wandb.ai/settings",
    ]
    for case in cases:
        ref = WandbReference.parse(case)
        assert ref.host == "beta.wandb.ai"
        assert ref.entity is None


def test_parse_run():
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


def test_parse_run_bare():
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


def test_parse_job():
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


def test_parse_job_bare():
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


def test_is_uri_job_or_run():
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
