"""
multiproc full tests.
"""

import multiprocessing
import platform
import pytest
import time

import six
import wandb


def train(add_val):
    time.sleep(1)
    wandb.log(dict(mystep=1, val=2 + add_val))
    wandb.log(dict(mystep=2, val=8 + add_val))
    wandb.log(dict(mystep=3, val=3 + add_val))
    wandb.log(dict(val2=4 + add_val))
    wandb.log(dict(val2=1 + add_val))
    time.sleep(1)


def test_multiproc_default(live_mock_server, parse_ctx):
    run = wandb.init()
    train(0)
    run.finish()

    ctx_util = parse_ctx(live_mock_server.get_ctx())

    summary = ctx_util.summary
    s = {k: v for k, v in dict(summary).items() if not k.startswith("_")}
    assert dict(val=3, val2=1, mystep=3) == s


@pytest.mark.skipif(platform.system() == "Windows", reason="fork needed")
def test_multiproc_ignore(live_mock_server, parse_ctx):
    run = wandb.init()

    train(0)

    procs = []
    for i in range(2):
        procs.append(multiprocessing.Process(target=train, kwargs=dict(add_val=100)))

    try:
        for p in procs:
            p.start()
    finally:
        for p in procs:
            p.join()
            assert p.exitcode == 0

    run.finish()

    ctx_util = parse_ctx(live_mock_server.get_ctx())

    summary = ctx_util.summary
    s = {k: v for k, v in dict(summary).items() if not k.startswith("_")}
    assert dict(val=3, val2=1, mystep=3) == s


@pytest.mark.flaky
@pytest.mark.skipif(platform.system() == "Windows", reason="fork needed")
@pytest.mark.xfail(platform.system() == "Darwin", reason="console parse_ctx issues")
def test_multiproc_strict(live_mock_server, parse_ctx):
    run = wandb.init(settings=wandb.Settings(strict="true"))

    train(0)

    procs = []
    for i in range(2):
        procs.append(multiprocessing.Process(target=train, kwargs=dict(add_val=100)))

    try:
        for p in procs:
            p.start()
    finally:
        for p in procs:
            p.join()
            # expect fail
            assert p.exitcode != 0

    run.finish()

    ctx_util = parse_ctx(live_mock_server.get_ctx())

    summary = ctx_util.summary
    s = {k: v for k, v in dict(summary).items() if not k.startswith("_")}
    assert dict(val=3, val2=1, mystep=3) == s


def test_multiproc_strict_bad(live_mock_server, parse_ctx):
    with pytest.raises(TypeError):
        run = wandb.init(settings=wandb.Settings(strict="bad"))
