"""sample tests."""

from __future__ import print_function

import pytest

import wandb

sample = wandb.wandb_sdk.internal.sample


def doit(num, samples=None):
    s = sample.UniformSampleAccumulator(min_samples=samples)
    for n in range(num):
        s.add(n)
    return s.get()


def diff(l):
    d = []
    for n, v in enumerate(l[1:]):
        d.append(v - l[n])
    return d


def check(n, l, samples):
    d = diff(l)
    diffs = set(d)
    if len(l) < 2:
        return
    assert len(diffs) == 1
    assert len(l) == n or (len(l) >= samples and len(l) <= samples * 3)


def test_all():
    """Try all."""
    for s in range(1, 36, 7):
        for n in range(1000):
            l = doit(n, samples=s)
            check(n, l, samples=s)
