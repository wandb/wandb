from wandb.apis.public import Api as PublicApi


def test_job_call(user, wandb_init, test_settings):
    proj = "TEST_PROJECT"
    public_api = PublicApi()
    settings = test_settings({"project": proj})
    run = wandb_init(settings=settings)

    docker_image = "TEST_IMAGE"
    job_artifact = run._log_job_artifact_with_image(docker_image)
    job_name = job_artifact.wait().name
    job = public_api.job(f"{user}/{proj}/{job_name}")

    queued_run = job.call(config={}, project=proj)
    run.finish()

    assert queued_run.state == "pending"
    assert queued_run.entity == user
    assert queued_run.project == proj
    assert queued_run.container_job is True
