"""
multiproc full tests.
"""

import multiprocessing
import time

import six
import wandb


def test_multiproc_default(live_mock_server, parse_ctx):
    run = wandb.init()
    run.log(dict(mystep=1, val=2))
    run.log(dict(mystep=2, val=8))
    run.log(dict(mystep=3, val=3))
    run.log(dict(val2=4))
    run.log(dict(val2=1))
    run.finish()

    ctx_util = parse_ctx(live_mock_server.get_ctx())

    summary = ctx_util.summary
    s = {k: v for k, v in dict(summary).items() if not k.startswith("_")}
    assert dict(val=3, val2=1, mystep=3) == s


def test_multiproc_ignore(live_mock_server, parse_ctx):
    def train():
        time.sleep(1)
        wandb.log(dict(ignore1=2))
        wandb.log(dict(ignore1=3))
        time.sleep(1)
    run = wandb.init()

    run.log(dict(mystep=1, val=2))
    run.log(dict(mystep=2, val=8))
    run.log(dict(mystep=3, val=3))
    run.log(dict(val2=4))
    run.log(dict(val2=1))

    procs = []
    for i in range(2):
        procs.append(multiprocessing.Process(target=train))

    for p in procs:
        p.start()
    for p in procs:
        p.join()

    run.finish()

    ctx_util = parse_ctx(live_mock_server.get_ctx())

    summary = ctx_util.summary
    s = {k: v for k, v in dict(summary).items() if not k.startswith("_")}
    assert dict(val=3, val2=1, mystep=3) == s
