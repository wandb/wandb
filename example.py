import torch
import tensorflow
import wandb


def main():
    run = wandb.init()
    import sklearn

    run.finish()

    run1 = wandb.init()
    import xgboost

    run1.finish()


if __name__ == "__main__":
    main()
