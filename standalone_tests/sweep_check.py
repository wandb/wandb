#!/usr/bin/env python

from __future__ import print_function

import wandb
import time
import shutil
import os
import argparse
import requests

L = 10
PROJECT="standalone-sweep-check"
POKE_LOCAL = False

URL="http://localhost:9002/admin/early_stop"

def poke():
    f = requests.get(URL)
    data = f.text
    print("GOT:", data)


def train(**kwargs):
    print("train", kwargs)
    if kwargs.get("chdir"):
        try:
            os.makedirs('./test_chdir')
        except:
            pass
        os.chdir('./test_chdir')
    run = wandb.init()
    with run:
        c=dict(run.config)
        run.name = '{}-{}-{}'.format(c.get("param0"), c.get("param1"), c.get("param2"))
        run_id = run.id
        print("SweepID", run.sweep_id)
        length = run.config.get("length", L)
        epochs = run.config.get("epochs", 27)
        delay = run.config.get("delay", 0)
        for e in range(epochs):
            n = float(length) * (float(e+1) / epochs)
            val = run.config.param0 + run.config.param1 * n + run.config.param2 * n * n
            wandb.log(dict(val_acc=val))
            if delay:
                time.sleep(delay)
            if POKE_LOCAL:
                poke()
    shutil.copyfile("wandb/debug.log", "wandb/debug-%s.log" % run_id)

# WB-3321: check if sweeps work when a user uses os.chdir in sweep function
def train_and_check_chdir(**kwargs):
    if 'test_chdir' not in os.getcwd():
        try:
            os.makedirs('./test_chdir')
        except:
            pass
        os.chdir('./test_chdir')
    run = wandb.init()
    with run:
        c=dict(run.config)
        root = c.get('root')
        run.name = '{}-{}-{}'.format(c.get("param0"), c.get("param1"), c.get("param2"))
        run_id = run.id
        print("SweepID", run.sweep_id)
        length = run.config.get("length", L)
        epochs = run.config.get("epochs", 27)
        for e in range(epochs):
            n = float(length) * (float(e+1) / epochs)
            val = run.config.param0 + run.config.param1 * n + run.config.param2 * n * n
            wandb.log(dict(val_acc=val))
        files = os.listdir(run.dir)
        # TODO: Add a check to restoring from another run in this case, WB-3715. Should restore to run.dir
        # check files were saved to the right place
        assert set(files) == set(['requirements.txt', 'output.log', 'config.yaml', 'wandb-summary.json', 'wandb-metadata.json']), print(files)
        # ensure run dir does not contain test_chdir, and no files were saved there
        assert 'test_chdir' not in run.dir
        for root, dir, files in os.walk("."):
            assert files == [], print(files)


def check(sweep_id, num=None, result=None, stopped=None):
    settings = wandb.InternalApi().settings()
    api = wandb.Api(overrides=settings)
    sweep = api.sweep("%s/%s" % (PROJECT, sweep_id))
    runs = sorted(sweep.runs, key=lambda run: run.summary.get("val_acc", 0), reverse=True)
    if num is not None:
        print("CHECKING: runs, saw: {}, expecting: {}".format(len(runs), num))
        assert len(runs) == num
    val_acc = None
    cnt_stopped = 0
    for run in runs:
        print("stop debug", run.id, getattr(run, "stopped", None), run.state)
        if getattr(run, "stopped", None) or run.state == "stopped":
            cnt_stopped += 1
        tmp = run.summary.get("val_acc")
        assert tmp is not None
        val_acc = tmp if val_acc is None or tmp > val_acc else val_acc
    if stopped is not None:
        print("NOT CHECKING: stopped, saw: {}, expecting: {}".format(cnt_stopped, stopped))
        # FIXME: turn on stopped run state
    if result is not None:
        print("CHECKING: metric, saw: {}, expecting: {}".format(val_acc, result))
        assert val_acc == result
    print("ALL GOOD")


def sweep_quick(args):
    config = dict(
        method="random",
        parameters=dict(
            param0=dict(values=[2]),
            param1=dict(values=[0, 1, 4]),
            param2=dict(values=[0, 0.5, 1.5]),
            epochs=dict(value=4),
            )
        )
    sweep_id = wandb.sweep(config, project=PROJECT)
    print("sweep:", sweep_id)
    wandb.agent(sweep_id, function=train, count=1)
    check(sweep_id, num=1)


def sweep_grid(args):
    config = dict(
        method="grid",
        parameters=dict(
            param0=dict(values=[2]),
            param1=dict(values=[0, 1, 4]),
            param2=dict(values=[0, 0.5, 1.5]),
            epochs=dict(value=4),
            )
        )
    sweep_id = wandb.sweep(config, project=PROJECT)
    print("sweep:", sweep_id)
    wandb.agent(sweep_id, function=train)
    check(sweep_id, num=9, result=2 + 4*L + 1.5*L*L)


def sweep_bayes(args):
    config = dict(
        method="bayes",
        metric=dict(name="val_acc", goal="maximize"),
        parameters=dict(
            param0=dict(values=[2]),
            param1=dict(values=[0, 1, 4]),
            param2=dict(values=[0, 0.5, 1.5]),
            )
        )
    sweep_id = wandb.sweep(config, project=PROJECT)
    print("sweep:", sweep_id)
    wandb.agent(sweep_id, function=train, count=9)
    check(sweep_id, num=9, result=2 + 4*L + 1.5*L*L)


def sweep_bayes_nested(args):
    config = dict(
        method="bayes",
        metric=dict(name="feat1.val_acc", goal="maximize"),
        parameters=dict(
            param0=dict(values=[2]),
            param1=dict(values=[0, 1, 4]),
            param2=dict(values=[0, 0.5, 1.5]),
            )
        )
    sweep_id = wandb.sweep(config, project=PROJECT)
    print("sweep:", sweep_id)
    wandb.agent(sweep_id, function=train_nested, count=9)
    check(sweep_id, num=9, result=2 + 4*L + 1.5*L*L)


def sweep_grid_hyperband(args):
    config = dict(
        method="grid",
        metric=dict(name="val_acc", goal="maximize"),
        parameters=dict(
            param0=dict(values=[2]),
            param1=dict(values=[4, 1, 0]),
            param2=dict(values=[1.5, 0.5, 0]),
            delay=dict(value=args.grid_hyper_delay or 1),
            epochs=dict(value=27),
            ),
        early_terminate=dict(
            type="hyperband",
            max_iter=27,
            s=2,
            eta=3
            ),
        )
    sweep_id = wandb.sweep(config, project=PROJECT)
    print("sweep:", sweep_id)
    wandb.agent(sweep_id, function=train, count=9)
    # TODO(check stopped)
    check(sweep_id, num=9, result=2 + 4*L + 1.5*L*L, stopped=3)

# test that files are saved in the right place when there is an os.chdir during a sweep function
def sweep_chdir(args):
    config = dict(
        method="grid",
        parameters=dict(
            param0=dict(values=[2]),
            param1=dict(values=[0, 1, 4]),
            param2=dict(values=[0, 0.5, 1.5]),
            epochs=dict(value=4),
            ),
        root=os.getcwd()
        )

    sweep_id = wandb.sweep(config, project=PROJECT)
    wandb.agent(sweep_id, function=train_and_check_chdir, count=2)
    # clean up
    os.chdir('../')
    os.removedirs('./test_chdir')


def main():
    global POKE_LOCAL
    #os.environ["WANDB_DEBUG"] = "true"
    parser = argparse.ArgumentParser()
    parser.add_argument('-t', '--test', default='', type=str)
    parser.add_argument('-x', '--exclude', default='', type=str)
    parser.add_argument('--grid_hyper_delay', type=int)
    parser.add_argument('--dryrun', dest='dryrun', action='store_true')
    parser.add_argument('--local', dest='local', action='store_true')
    args = parser.parse_args()

    all_tests = dict(
            quick=sweep_quick,
            grid=sweep_grid,
            bayes=sweep_bayes,
            grid_hyper=sweep_grid_hyperband,
            chdir=sweep_chdir,
            )
    default_tests = ('quick', 'grid', 'bayes', 'chdir')
    test_list = args.test.split(',') if args.test else default_tests
    exclude_list = args.exclude.split(',') if args.exclude else []

    for t in test_list:
        POKE_LOCAL = False
        if t in exclude_list:
            continue
        print("Testing: {}".format(t))
        f = all_tests.get(t)
        if f is None:
            raise Exception("Unknown test: %s" % t)
        if args.dryrun:
            continue
        if args.local and t == 'grid_hyper':
            POKE_LOCAL = True
        f(args)


if __name__ == "__main__":
    main()

