import wandb


if __name__ == "__main__":
    run = wandb.init(mode="offline")
    run.finish()
