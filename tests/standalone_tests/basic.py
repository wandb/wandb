import pathlib

import wandb


def main():
    run = wandb.init(name=pathlib.Path(__file__).stem)
    run.log({"boom": 1})
    run.finish()


if __name__ == "__main__":
    main()
