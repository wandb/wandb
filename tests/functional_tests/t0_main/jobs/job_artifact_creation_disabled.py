import wandb

settings = wandb.Settings()
settings.update({"job_source": "artifact", "disable_job_creation": True})
run = wandb.init(
    project="test-job", config={"foo": "bar", "lr": 0.1, "epochs": 5}, settings=settings
)
for i in range(1, run.config["epochs"]):
    wandb.log({"loss": i})
    run.log_code()
run.finish()
