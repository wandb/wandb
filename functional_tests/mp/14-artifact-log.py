#!/usr/bin/env python

import wandb


def main():
    wandb.require("service")
    run = wandb.init()
    run.log(dict(m1=1))
    run.log(dict(m2=2))

    with open("my-dataset.txt", "w") as fp:
        fp.write("this-is-data")
    artifact = wandb.Artifact('my-dataset', type='dataset')
    artifact.add_file('my-dataset.txt')
    run.log_artifact(artifact)
    run.finish()


if __name__ == "__main__":
    main()
