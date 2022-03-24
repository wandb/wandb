import wandb
import argparse
import os


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-e", type=int, default=10)
    parser.add_argument("-lr", type=float, default=0.01)
    parser.add_argument("-b", type=float, default=2)
    args, _ = parser.parse_known_args()
    run_id = os.environ.get("WANDB_RUN_ID")
    run = wandb.init(
        config={"epochs": args.e, "lr": args.lr, "b": args.b},
        group="test",
        project="multi-run-test",
        id=run_id,
        reinit=True,
        resume=True,
    )

    for i in range(run.config.epochs):
        run.log({"epoch": i, "eval_loss": i * run.config.b - i * run.config.lr})
    run.finish()


if __name__ == "__main__":
    main()
