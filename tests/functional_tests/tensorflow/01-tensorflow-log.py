import os

import wandb


def main():
    wandb.init()

    summary_pb_filename = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        os.pardir,
        os.pardir,
        "tests",
        "wandb_tensorflow_summary.pb",
    )
    summary_pb = open(summary_pb_filename, "rb").read()

    wandb.tensorboard.log(summary_pb)


if __name__ == "__main__":
    main()
