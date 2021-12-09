import wandb

run = wandb.init()

wb_model = wandb.Model(None)
artifact = wandb.Artifact("test-artifact", "model")
artifact.add(wb_model, "dummy-model")

print(artifact.manifest.entries)

run.log_artifact(artifact)
run.finish()


run = wandb.init()
artifact = wandb.use_artifact("test-artifact:latest")
print(artifact.manifest.entries)
