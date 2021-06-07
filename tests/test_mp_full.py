from __future__ import print_function

"""
multiproc full tests.
"""

import importlib
import multiprocessing
import platform
import pytest
import time
import wandb
import sys


def train(add_val):
    time.sleep(1)
    wandb.log(dict(mystep=1, val=2 + add_val))
    wandb.log(dict(mystep=2, val=8 + add_val))
    wandb.log(dict(mystep=3, val=3 + add_val))
    wandb.log(dict(val2=4 + add_val))
    wandb.log(dict(val2=1 + add_val))
    time.sleep(1)


def test_multiproc_default(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    train(0)
    run.finish()

    ctx_util = parse_ctx(live_mock_server.get_ctx())

    summary = ctx_util.summary
    s = {k: v for k, v in dict(summary).items() if not k.startswith("_")}
    assert dict(val=3, val2=1, mystep=3) == s


@pytest.mark.skipif(platform.system() == "Windows", reason="fork needed")
def test_multiproc_ignore(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)

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
def test_multiproc_strict(live_mock_server, test_settings, parse_ctx):
    test_settings.strict = "true"
    run = wandb.init(settings=test_settings)

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


def test_multiproc_strict_bad(live_mock_server, test_settings, parse_ctx):
    with pytest.raises(TypeError):
        test_settings.strict = "bad"


@pytest.mark.skipif(
    sys.version_info[0] < 3, reason="multiprocessing.get_context introduced in py3"
)
def test_multiproc_spawn(test_settings):
    # WB5640. Before the WB5640 fix this code fragment would raise an
    # exception, this test checks that it runs without error

    from .utils import test_mod

    test_mod.main()
    sys.modules["__main__"].__spec__ = importlib.machinery.ModuleSpec(
        name="tests.utils.test_mod", loader=importlib.machinery.BuiltinImporter
    )
    test_mod.main()
    sys.modules["__main__"].__spec__ = None
    # run this to get credit for the diff
    test_mod.mp_func()
