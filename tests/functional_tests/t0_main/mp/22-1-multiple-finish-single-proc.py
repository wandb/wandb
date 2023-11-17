import wandb

if __name__ == "__main__":
    with wandb.init() as run:
        run.finish()
    run.finish()
