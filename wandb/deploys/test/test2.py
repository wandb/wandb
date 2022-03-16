import wandb
import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-e", type=int, default=10)
    parser.add_argument("-lr", type=float, default=0.01)
    parser.add_argument("-b", type=float, default=2)
    args, _ = parser.parse_known_args()

    run = wandb.init(
        config={"epochs": args.e, "lr": args.lr, "b": args.b},
        group="test",
        project="multi-run-test",
    )

    for i in range(run.config.epochs):
        run.log({"epoch": i, "eval_loss": i * run.config.b - i * run.config.lr})
    run.finish()


if __name__ == "__main__":
    main()
