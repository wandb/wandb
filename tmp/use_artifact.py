import wandb

wandb.init()
artifact = wandb.use_artifact("test-artifact:latest")
print(artifact.__dict__)
