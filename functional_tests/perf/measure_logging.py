#!/usr/bin/env python

import multiprocessing as mp
from multiprocessing import Process, Queue, Pipe
from random import random
import traceback
import time
import six
import os
import argparse
import wandb
import datetime

PERF_PREFIX = "perf_"
PERF_PREFIX = "perf_tf2"
PERF_PREFIX = "perf_log_commit"

RECORD_PROJECT = "measure-logging"
PROJECT = "measure-logging-data"
ENTITY = ""
GROUP = ""
RECORD_NAME = ""

args = None

def getdatestr():
    now = datetime.datetime.now()
    return now.strftime("%Y%m%d%H%M")


class ExceptionProcess(Process):
    """Extend multiprocessing.Process to catch exceptions."""
    def __init__(self, *args, **kwargs):
        Process.__init__(self, *args, **kwargs)
        self._pconn, self._cconn = Pipe()
        self._exception = None

    def run(self):
        try:
            Process.run(self)
            self._cconn.send(None)
        except Exception as e:
            tb = traceback.format_exc()
            self._cconn.send((e, tb))
            # raise e  # You can still rise this exception if you need to

    @property
    def exception(self):
        if self._pconn.poll():
            self._exception = self._pconn.recv()
        return self._exception


def measure(func, num=None, step=0):
    """measure performance."""
    base_step = step
    num = num or 5000
    start_log = time.perf_counter()
    for step in range(num):
        func(step=step + base_step)
    end_log = time.perf_counter()
    return (end_log - start_log) / num


def wandb_perf_session(func):
    """decorator."""
    def wrapper(q, name):
        import wandb
        import os
        if name:
            os.environ["WANDB_NAME"] = name
        perf = func()
        wandb.join()
        q.put(perf)
    return wrapper


def wandb_env_tensorboardX(func):
    """decorator."""
    def wrapper():
        import wandb
        from tensorboardX import SummaryWriter
        wandb_init(sync_tensorboard=True)
        #wandb.tensorboard.patch(tensorboardX=True)
        writer = SummaryWriter()
        return func(writer=writer)
    return wrapper


def wandb_env_pt_tensorboard(func):
    """decorator."""
    def wrapper():
        import wandb
        from torch.utils.tensorboard import SummaryWriter
        wandb_init(sync_tensorboard=True)
        #wandb.tensorboard.patch(tensorboardX=True)
        writer = SummaryWriter()
        return func(writer=writer)
    return wrapper


def get_test_data(writer):
    import torch
    #import numpy as np
    data = (
            ('scaler', random(), lambda val : writer.add_scalar("loss", val), None),
            ('image', torch.ones((1, 28, 28)), lambda val : writer.add_image("image", val), None),
            ('bigimage', torch.ones((3, 1024, 1024)), lambda val : writer.add_image("bigimage", val), 100),
            #('video', np.random.random(size=(1, 5, 3, 28, 28)), lambda val : writer.add_video("video", val), 100),
            )
    return data


def wandb_init(**argv):
    wandb.init(reinit=True, group=os.environ.get("WANDB_RUN_GROUP", None), name=os.environ.get("WANDB_NAME", None), **argv)


@wandb_perf_session
@wandb_env_tensorboardX
def perf_pt_tensorboardX(writer):
    result = []
    data = get_test_data(writer)
    base = 0
    for name, val, f, num in data:
        if args.test_data and name not in args.test_data.split(','):
            continue
        perf = measure(lambda step : f(val), num=num, step=base)
        result.append((name, perf))
        base += 10000
    return result


@wandb_perf_session
@wandb_env_pt_tensorboard
def perf_pt_tensorboard_native(writer):
    result = []
    base = 0
    data = get_test_data(writer)
    for name, val, f, num in data:
        perf = measure(lambda step : f(val), num=num, step=base)
        result.append((name, perf))
        base += 10000
    return result


@wandb_perf_session
def perf_log_sync():
    import wandb
    wandb_init()
    perf = measure(lambda step : wandb.log({"me": 2}))
    return perf


@wandb_perf_session
def perf_log_async():
    import wandb
    wandb_init()
    perf = measure(lambda step : wandb.log({"me": 2}, sync=False))
    return perf


@wandb_perf_session
def perf_tf2_tensorboard():
    import tensorflow as tf
    import wandb
    wandb_init(sync_tensorboard=True)
    writer = tf.summary.create_file_writer("blah")
    base = 0
    import numpy as np
    image = np.random.random(size=(1, 28, 28, 3))
    with writer.as_default():
        data = np.float32(random())
        perf = measure(lambda step: tf.summary.scalar('loss', data=data, step=step), step=base)
        base += 10000
        perf = measure(lambda step: tf.summary.image('xpiz', data=image, step=step), step=base)
    return perf

def get_large_dict():
    d = {}
    for x in range(100):
        d[str(x)] = x
    return d

def log_commit_false(d):
    for k, v in d.items():
        wandb.log({k: v}, commit=False)
    wandb.log({})

def log_commit_true(d):
    wandb.log(d)

@wandb_perf_session
def perf_log_commit_false():
    import wandb
    wandb_init()
    d = get_large_dict()
    perf = measure(lambda step: log_commit_false(d))
    return perf

@wandb_perf_session
def perf_log_commit_true():
    import wandb
    wandb_init()
    d = get_large_dict()
    perf = measure(lambda step: log_commit_true(d))
    return perf


def run_all(funcs):
    results = []
    for name, f in funcs.items():
        os.environ["WANDB_NAME"] = name
        q = Queue()
        p = ExceptionProcess(target=f, args=(q,name))
        p.start()
        p.join()
        if p.exception:
            error, traceback = p.exception
            print("ERROR:", error)
            print("TRACEBACK:", traceback)
            results.append((name, "#ERROR#"))
            continue
        val = None
        try:
            val = q.get(block=False)
        except six.moves.queue.Empty:
            pass
        if isinstance(val, list):
            for n, v in val:
                results.append(("{}.{}".format(name, n), v))
        else:
            results.append((name, val))
    return results


def summary(report):
    print("Summary:")
    for k, v in report:
        print(k, v)


def main():
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--project", type=str, default=PROJECT, help="Project name")
    parser.add_argument("--entity", type=str, default=ENTITY, help="Entity name")
    parser.add_argument("--group", type=str, default=GROUP, help="Group name")
    parser.add_argument("--sync", default=False, dest="sync", help="Sync to backend", action="store_true")
    parser.add_argument("--record", default=True, dest="record", help="Record results", action="store_true")
    parser.add_argument("--no-record", default=False, dest="record", help="Record results", action="store_false")
    parser.add_argument("--record_project", type=str, default=RECORD_PROJECT, help="Record project")
    parser.add_argument("--record_name", type=str, default=RECORD_NAME, help="Record name")
    parser.add_argument("--test_prefix", type=str, default=None, help="Tests to run")
    parser.add_argument("--test_data", type=str, default=None, help="Test data to run")
    global args
    args = parser.parse_args()

    # https://stackoverflow.com/questions/55924761/worker-process-crashes-on-requests-get-when-data-is-put-into-input-queue-befor
    os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

    default_name = "{}-{}".format(wandb.__version__, getdatestr())

    if not args.sync:
        os.environ["WANDB_MODE"] = "dryrun"
    os.environ["WANDB_PROJECT"] = args.project
    os.environ["WANDB_RUN_GROUP"] = args.group or default_name

    funcs = {n: f for n, f in globals().items() if n.startswith(PERF_PREFIX) and (not args.test_prefix or n.startswith(args.test_prefix))}
    report = run_all(funcs)
    summary(report)

    if args.record:
        if not args.sync:
            del os.environ["WANDB_MODE"]
        del os.environ["WANDB_RUN_GROUP"]
        wandb.init(project=args.record_project, name=args.record_name or default_name)
        if args.sync:
            base_url = wandb.run.get_url().split(args.record_project)[0]
            record_group_url = base_url + args.project + "/groups/" + (args.group or default_name)
            notes = "Group:\n" + record_group_url
            wandb.run.notes = notes
            wandb.run.save()
        wandb.log(dict(report))


if __name__ == '__main__':
    mp.set_start_method("fork")
    main()
