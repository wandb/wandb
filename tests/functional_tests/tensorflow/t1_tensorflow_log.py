import os

import wandb


def main():
    wandb.init()
    test_dir = os.path.dirname(os.path.abspath(__file__))
    summary_pb_filename = os.path.join(
        test_dir,
        "wandb_tensorflow_summary.pb",
    )
    summary_pb = open(summary_pb_filename, "rb").read()

    wandb.tensorboard.log(summary_pb)


if __name__ == "__main__":
    main()
