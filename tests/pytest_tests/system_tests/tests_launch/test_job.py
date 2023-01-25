from wandb.apis.public import Api as PublicApi
from wandb.sdk.internal.internal_api import Api as InternalApi


def test_job_call(relay_server, user, wandb_init, test_settings):
    proj = "TEST_PROJECT"
    queue = "TEST_QUEUE"
    public_api = PublicApi()
    internal_api = InternalApi()
    settings = test_settings({"project": proj})

    with relay_server():
        run = wandb_init(settings=settings)

        docker_image = "TEST_IMAGE"
        job_artifact = run._log_job_artifact_with_image(docker_image)
        job_name = job_artifact.wait().name
        job = public_api.job(f"{user}/{proj}/{job_name}")

        internal_api.create_run_queue(
            entity=user, project=proj, queue_name=queue, access="PROJECT"
        )

        queued_run = job.call(config={}, project=proj, queue=queue, project_queue=proj)

        assert queued_run.state == "pending"
        assert queued_run.entity == user
        assert queued_run.project == proj
        assert queued_run.container_job is True

        rqi = internal_api.pop_from_run_queue(queue, user, proj)

        assert rqi["runSpec"]["job"].split("/")[-1] == f"job-{docker_image}:v0"
        assert rqi["runSpec"]["project"] == proj
        run.finish()
