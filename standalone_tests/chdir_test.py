#!/usr/bin/env python
"""
Test for WB-3758.
"""

import os
import sys

import wandb

def main(argv):
    # test to ensure
    run = wandb.init()
    run_project = run.project
    run_id = run.id
    print("Started run {}/{}".format(run_project, run_id))

    try:
        os.makedirs('./chdir_test')
    except Exception as e:
        pass

    os.chdir('./chdir_test')
    # log some table data, which is saved in the media folder
    pr_data = [
        ['setosa', 1.0, 1.0], ['setosa', 1.0, 1.0], ['setosa', 1.0, 1.0], ['setosa', 1.0, 1.0], ['setosa', 1.0, 1.0],
        ['setosa', 1.0, 1.0], ['setosa', 1.0, 1.0], ['setosa', 1.0, 1.0], ['setosa', 1.0, 1.0], ['setosa', 1.0, 1.0],
        ['setosa', 1.0, 0.0], ['setosa', 1.0, 0.0], ['setosa', 1.0, 0.0], ['setosa', 1.0, 0.0], ['setosa', 1.0, 0.0],
        ['setosa', 1.0, 0.0], ['setosa', 1.0, 0.0], ['setosa', 1.0, 0.0], ['setosa', 1.0, 0.0], ['setosa', 1.0, 0.0],
        ['versicolor', 1.0, 1.0], ['versicolor', 1.0, 1.0], ['versicolor', 1.0, 1.0], ['versicolor', 1.0, 1.0],
        ['versicolor', 1.0, 1.0], ['versicolor', 1.0, 1.0], ['versicolor', 1.0, 1.0], ['versicolor', 1.0, 1.0],
        ['versicolor', 1.0, 1.0], ['versicolor', 1.0, 1.0], ['versicolor', 1.0, 0.0], ['versicolor', 1.0, 0.0],
        ['versicolor', 1.0, 0.0], ['versicolor', 1.0, 0.0], ['versicolor', 1.0, 0.0], ['versicolor', 1.0, 0.0],
        ['versicolor', 1.0, 0.0], ['versicolor', 1.0, 0.0], ['versicolor', 1.0, 0.0], ['versicolor', 1.0, 0.0]
        ]

    # convert the data to a table
    pr_table = wandb.Table(data=pr_data, columns=["class", "precision", "recall"])
    wandb.log({'pr_table': pr_table})
    wandb.finish()

    # Check results
    api = wandb.Api()
    last_run = api.run("%s/%s" % (run_project, run_id))
    media_path = last_run.summary_metrics["pr_table"]["path"]
    media_file = last_run.file(media_path)
    assert media_file.size > 0
    print("Success")

if __name__ == '__main__':
    main(sys.argv)
