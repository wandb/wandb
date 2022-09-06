"""sample tests."""


import wandb

sample = wandb.wandb_sdk.internal.sample


def doit(num, samples=None):
    s = sample.UniformSampleAccumulator(min_samples=samples)
    for n in range(num):
        s.add(n)
    return s.get()


def diff(sampled):
    d = []
    for n, v in enumerate(sampled[1:]):
        d.append(v - sampled[n])
    return d


def check(n, sampled, samples):
    d = diff(sampled)
    diffs = set(d)
    if len(sampled) < 2:
        return
    assert len(diffs) == 1
    assert len(sampled) == n or (
        len(sampled) >= samples and len(sampled) <= samples * 3
    )


def test_all():
    """Try all."""
    for s in range(1, 36, 7):
        for n in range(1000):
            sampled = doit(n, samples=s)
            check(n, sampled, samples=s)
