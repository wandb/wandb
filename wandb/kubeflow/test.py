import wandb

wandb.init(project="test_summary")

#wandb.run.summary.update({"summary_val": 10})

for i in range(10):
    wandb.log({"log_val": i})

print("Finished")
