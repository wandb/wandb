import wandb

settings = wandb.Settings()
settings.update(
    {"disable_git": True, "enable_job_creation": True}, job_name="test-job-name"
)
run = wandb.init(
    project="test-job", config={"foo": "bar", "lr": 0.1, "epochs": 5}, settings=settings
)
for i in range(1, run.config["epochs"]):
    wandb.log({"loss": i})
run.log_code()
run.finish()
