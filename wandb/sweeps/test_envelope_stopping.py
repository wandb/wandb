import numpy as np
from numpy.random import uniform
from numpy.random import randint
from wandb.sweeps import envelope_stopping


def synthetic_loss(start, asympt, decay, noise, length):
    val = start
    history = []
    metric = []
    for ii in range(length):
        history.append(val)
        val += uniform(-noise, noise)
        val -= (val - asympt) * decay
    return history


def synthetic_loss_random():
    return synthetic_loss(
        uniform(4, 20), uniform(1, 2), uniform(0.05, 0.4), 0.5, randint(10, 20)
    )


def synthetic_loss_family(num):
    histories = []
    for ii in range(num):
        history = synthetic_loss(
            uniform(4, 20), uniform(2, 3.), uniform(0.05, 0.4), 0.5, randint(10, 20)
        )
        histories.append(history)
    return histories


def test_envelope_terminate():
    hs = synthetic_loss_family(20)
    m = []
    for h in hs:
        m.append(min(h))
    top_hs = envelope_stopping.histories_for_top_n(hs, m, 5)
    envelope = envelope_stopping.envelope_from_histories(top_hs, 30)
    tries = 10
    for i in range(tries):
        new_history = synthetic_loss(
            20 + uniform(4, 20), 20., uniform(0.05, 0.4), 0.5, randint(10, 40)
        )
        assert (not envelope_stopping.is_inside_envelope(new_history, envelope))
    for i in range(tries):
        new_history = synthetic_loss(
            uniform(0, 2.), 20., uniform(0, 1.), 0.5, randint(10, 50)
        )
        print(new_history)
        print(envelope)
        assert envelope_stopping.is_inside_envelope(new_history, envelope)
