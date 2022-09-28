"""
rm -rf wandb \
 && WANDB_BASE_URL=http://api.wandb.test python offline_artifacts.py \
 && rm -rf wandb \
 && WANDB_BASE_URL=http://api.wandb.test python offline_artifacts.py --online
"""

import sys

import numpy as np
import wandb
from click.testing import CliRunner
from wandb.cli import cli

dataset_size = 250
pred_size = 100
mode = "offline" if len(sys.argv) <= 1 or sys.argv[1] != "--online" else "online"
project = f"offline_artifacts_2_{mode}"


def random_image():
    return wandb.Image(np.random.randint(255, size=(32, 32)))


def make_dataset():
    return wandb.Table(
        data=[[str(i), random_image()] for i in range(dataset_size)],
        columns=["id", "input_image"],
    )


def make_linked_table(dataset):
    tab = wandb.Table(
        data=[
            [str(np.random.choice(range(dataset_size)).tolist()), i, random_image()]
            for i in range(pred_size)
        ],
        columns=["fk_id", "tab_id", "pred_img"],
    )
    tab.set_fk("fk_id", dataset, "id")
    return tab


def make_run():
    return wandb.init(project=project, mode=mode)


# BASE RUN TYPES


def init_dataset_run():
    run = make_run()
    dataset = make_dataset()
    art = wandb.Artifact("A", "B")
    art.add(dataset, "dataset")
    run.log_artifact(art)
    run.finish()
    return dataset


def init_ref_dataset_run():
    run = make_run()
    dataset = make_dataset()
    tab = make_linked_table(dataset)
    run.log({"tab": tab})
    run.finish()
    return dataset


# ALTERNATE ORDERINGS (Should execute)


def do_ref_dataset_run_grouped():
    run = make_run()
    dataset = make_dataset()
    tab = make_linked_table(dataset)
    run.log({"dataset": dataset, "tab": tab})
    run.finish()
    return dataset


def do_ref_dataset_run_ordered():
    run = make_run()
    dataset = make_dataset()
    tab = make_linked_table(dataset)
    run.log({"dataset": dataset})
    run.log({"tab": tab})
    run.finish()
    return dataset


def do_ref_dataset_run_reversed():
    run = make_run()
    dataset = make_dataset()
    tab = make_linked_table(dataset)
    run.log({"tab": tab})
    run.log({"dataset": dataset})
    run.finish()
    return dataset


# DEP RUNS ON LOGGED


def do_dep_dataset_run():
    dataset = init_dataset_run()
    run = make_run()
    run.log({"dataset": dataset})
    run.finish()
    return run


def do_dep_ref_dataset_run():
    dataset = init_dataset_run()
    run = make_run()
    tab = make_linked_table(dataset)
    run.log({"tab": tab})
    run.finish()
    return run


def do_dep_ref_dataset_run_grouped():
    dataset = init_dataset_run()
    run = make_run()
    tab = make_linked_table(dataset)
    run.log({"dataset": dataset, "tab": tab})
    run.finish()
    return run


def do_dep_ref_dataset_run_ordered():
    dataset = init_dataset_run()
    run = make_run()
    tab = make_linked_table(dataset)
    run.log({"dataset": dataset})
    run.log({"tab": tab})
    run.finish()
    return run


def do_dep_ref_dataset_run_reversed():
    dataset = init_dataset_run()
    run = make_run()
    tab = make_linked_table(dataset)
    run.log({"tab": tab})
    run.log({"dataset": dataset})
    run.finish()
    return run


# DEP RUNS ON REF


def do_r_dep_dataset_run():
    dataset = init_ref_dataset_run()
    run = make_run()
    run.log({"dataset": dataset})
    run.finish()
    return run


def do_r_dep_ref_dataset_run():
    dataset = init_ref_dataset_run()
    run = make_run()
    tab = make_linked_table(dataset)
    run.log({"tab": tab})
    run.finish()
    return run


def do_r_dep_ref_dataset_run_grouped():
    dataset = init_ref_dataset_run()
    run = make_run()
    tab = make_linked_table(dataset)
    run.log({"dataset": dataset, "tab": tab})
    run.finish()
    return run


def do_r_dep_ref_dataset_run_ordered():
    dataset = init_ref_dataset_run()
    run = make_run()
    tab = make_linked_table(dataset)
    run.log({"dataset": dataset})
    run.log({"tab": tab})
    run.finish()
    return run


def do_r_dep_ref_dataset_run_reversed():
    dataset = init_ref_dataset_run()
    run = make_run()
    tab = make_linked_table(dataset)
    run.log({"tab": tab})
    run.log({"dataset": dataset})
    run.finish()
    return run


def sync_all():
    print("Syncing...")
    ctx = CliRunner()
    result = ctx.invoke(cli.sync, args=["--sync-all"])
    assert result.exit_code == 0
    print("...Syncing Complete")


def main():
    # Base Cases
    init_dataset_run()
    init_ref_dataset_run()

    # Alt Log Ordering
    do_ref_dataset_run_grouped()
    do_ref_dataset_run_ordered()
    do_ref_dataset_run_reversed()

    # Depend on base case 1
    do_dep_dataset_run()
    do_dep_ref_dataset_run()
    do_dep_ref_dataset_run_grouped()
    do_dep_ref_dataset_run_ordered()
    do_dep_ref_dataset_run_reversed()

    # Depend on base case 2
    do_r_dep_dataset_run()
    do_r_dep_ref_dataset_run()
    do_r_dep_ref_dataset_run_grouped()
    do_r_dep_ref_dataset_run_ordered()
    do_r_dep_ref_dataset_run_reversed()
    sync_all()


if __name__ == "__main__":
    main()
