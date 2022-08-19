"""
pip uninstall wandb > /dev/null -y && \
pip install wandb > /dev/null && \
WANDB_SILENT=true python artifact_table_load.py --n_rows=100 --img_dim=100 && \
WANDB_SILENT=true python artifact_table_load.py --n_rows=100 --img_dim=100 --clear_cache && \
WANDB_SILENT=true python artifact_table_load.py --n_rows=100 --img_dim=200 && \
WANDB_SILENT=true python artifact_table_load.py --n_rows=100 --img_dim=200 --clear_cache && \
WANDB_SILENT=true python artifact_table_load.py --n_rows=5000 --img_dim=100 && \
WANDB_SILENT=true python artifact_table_load.py --n_rows=5000 --img_dim=100 --clear_cache && \
WANDB_SILENT=true python artifact_table_load.py --n_rows=5000 --img_dim=200 && \
WANDB_SILENT=true python artifact_table_load.py --n_rows=5000 --img_dim=200 --clear_cache && \
pip uninstall wandb -y > /dev/null && \
pip install git+git://github.com/wandb/wandb.git@tim/artifacts/table_eager_download > /dev/null && \
WANDB_SILENT=true python artifact_table_load.py --n_rows=100 --img_dim=100 && \
WANDB_SILENT=true python artifact_table_load.py --n_rows=100 --img_dim=100 --clear_cache && \
WANDB_SILENT=true python artifact_table_load.py --n_rows=100 --img_dim=200 && \
WANDB_SILENT=true python artifact_table_load.py --n_rows=100 --img_dim=200 --clear_cache && \
WANDB_SILENT=true python artifact_table_load.py --n_rows=5000 --img_dim=100 && \
WANDB_SILENT=true python artifact_table_load.py --n_rows=5000 --img_dim=100 --clear_cache && \
WANDB_SILENT=true python artifact_table_load.py --n_rows=5000 --img_dim=200 && \
WANDB_SILENT=true python artifact_table_load.py --n_rows=5000 --img_dim=200 --clear_cache
"""

import argparse
import os
import shutil
import time

import numpy as np
import wandb
from wandb.sdk.interface import artifacts


def build_table(n_rows, img_dim):
    return wandb.Table(
        columns=["id", "image"],
        data=[
            [i, wandb.Image(np.random.randint(0, 255, size=(img_dim, img_dim)))]
            for i in range(n_rows)
        ],
    )


def safe_remove_dir(dir_name):
    if dir_name not in [".", "~", "/"] and os.path.exists(dir_name):
        shutil.rmtree(dir_name)


def delete_cache():
    safe_remove_dir("./artifacts")
    safe_remove_dir("~/.cache/wandb")
    safe_remove_dir(artifacts.get_artifacts_cache()._cache_dir)


def cleanup():
    delete_cache()
    safe_remove_dir("./wandb")


def main(n_rows, img_dim, clear_cache=False):
    timer = {
        "LOG_TABLE": [None, None],
        "GET_TABLE": [None, None],
        "LOG_REF": [None, None],
        "GET_REF": [None, None],
    }
    delete_cache()
    with wandb.init() as run:
        table = build_table(n_rows, img_dim)
        artifact = wandb.Artifact("table_load_test", "table_load_test")
        artifact.add(table, "table")
        timer["LOG_TABLE"][0] = time.time()
        run.log_artifact(artifact)
    timer["LOG_TABLE"][1] = time.time()

    if clear_cache:
        delete_cache()
    with wandb.init() as run:
        artifact = run.use_artifact("table_load_test:latest")
        timer["GET_TABLE"][0] = time.time()
        table = artifact.get("table")
        timer["GET_TABLE"][1] = time.time()
        artifact = wandb.Artifact("table_load_test_ref", "table_load_test")
        artifact.add(table, "table_ref")
        timer["LOG_REF"][0] = time.time()
        run.log_artifact(artifact)
    timer["LOG_REF"][1] = time.time()

    if clear_cache:
        delete_cache()
    with wandb.init() as run:
        artifact = run.use_artifact("table_load_test_ref:latest")
        timer["GET_REF"][0] = time.time()
        table = artifact.get("table_ref")
        timer["GET_REF"][1] = time.time()

    print(
        "Version      \tRows\tImgDim\tMBs\tCleared\tLOG_TAB\tGET_TAB\tLOG_REF\tGET_REF\t"
    )
    print(
        "{:13}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t".format(
            wandb.__version__,
            n_rows,
            img_dim,
            round(n_rows * (img_dim * img_dim) / 1000000, 1),
            clear_cache,
            round(timer["LOG_TABLE"][1] - timer["LOG_TABLE"][0], 3),
            round(timer["GET_TABLE"][1] - timer["GET_TABLE"][0], 3),
            round(timer["LOG_REF"][1] - timer["LOG_REF"][0], 3),
            round(timer["GET_REF"][1] - timer["GET_REF"][0], 3),
        )
    )

    cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n_rows", type=int, default=1000)
    parser.add_argument("--img_dim", type=int, default=100)
    parser.add_argument("--clear_cache", dest="clear_cache", action="store_true")
    args = vars(parser.parse_args())
    print(args)
    main(**args)
