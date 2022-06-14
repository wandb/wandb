import wandb

run = wandb.init(project="test-job", config={"foo": "bar", "lr": 0.1, "epochs": 5})
for i in range(1, run.config["epochs"]):
    wandb.log({"loss": i})
