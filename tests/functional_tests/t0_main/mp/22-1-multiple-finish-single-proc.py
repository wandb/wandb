import wandb

if __name__ == "__main__":
    wandb.require("service")

    with wandb.init() as run:
        run.finish()
    run.finish()
