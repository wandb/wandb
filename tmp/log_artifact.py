import wandb

wandb.init()
wb_model = wandb.Model(None)
artifact = wandb.Artifact("test-artifact", "model")
artifact.add(wb_model, "dummy-model")
print(artifact.manifest.entries)
wandb.log_artifact(artifact)
