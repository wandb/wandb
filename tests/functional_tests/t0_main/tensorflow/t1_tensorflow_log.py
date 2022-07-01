import os

import wandb


def main():
    wandb.init()
    test_dir = os.path.abspath(
        os.path.join(os.path.abspath(__file__), os.pardir, os.pardir, os.pardir, os.pardir)
    )
    summary_pb_filename = os.path.join(
        test_dir,
        "assets",
        "wandb_tensorflow_summary.pb",
    )
    summary_pb = open(summary_pb_filename, "rb").read()

    wandb.tensorboard.log(summary_pb)


if __name__ == "__main__":
    main()
