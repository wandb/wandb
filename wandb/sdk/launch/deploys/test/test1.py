import wandb
import argparse
import os


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-e", type=int, default=10)
    parser.add_argument("-lr", type=float, default=0.01)
    parser.add_argument("-a", type=float, default=2)
    args, _ = parser.parse_known_args()
    run_id = os.environ.get("WANDB_RUN_ID")
    wandb.termlog(run_id)
    run = wandb.init(
        config={"epochs": args.e, "lr": args.lr, "a": args.a},
        group="test",
        project="multi-run-test",
        id=run_id,
        reinit=True,
        resume=True,
    )

    for i in range(run.config.epochs):
        run.log({"epoch": i, "train_loss": i * run.config.a - i * run.config.lr})

    run.finish()


if __name__ == "__main__":
    main()
