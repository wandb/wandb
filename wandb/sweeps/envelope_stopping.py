"""
Envelope Early Terminate

Library to help with early termination of runs
Here we use a strategy where we take the top k runs or top k percent of runs
and then we build up an envelope where we stop jobs where the metric doesn't get better
"""

import numpy as np
from wandb.sweeps.base import EarlyTerminate


def top_k_indicies(arr, k):
    return np.argpartition(arr, -k)[-k:]


def cumulative_min(history, envelope_len):
    cur_min = np.inf
    cum_min = []
    for j in range(envelope_len):
        if j < len(history):
            val = history[j]
        else:
            val = np.nan
        cur_min = min(cur_min, val)
        cum_min.append(cur_min)
    return cum_min


def histories_for_top_n(histories, metrics, n=3):
    metrics = np.array(metrics)
    histories = np.array(histories)
    indices = top_k_indicies(-metrics, n)
    top_n_histories = []
    for index in indices:
        top_n_histories.append(histories[index])
    return top_n_histories


def envelope_from_histories(histories, envelope_len):
    envelope = []
    cum_min_hs = []
    longest = 0
    for h in histories:
        cum_min_hs.append(cumulative_min(h, envelope_len))
    for jj in range(envelope_len):
        prev_max = -np.inf
        if (len(envelope) > 0):
            prev_max = max(envelope)
        envelope.append(max([h[jj] for h in cum_min_hs]))
    return envelope


def envelope_from_top_n(histories, metrics, n):
    histories = histories_for_top_n(histories, metrics, n)
    envelope_len = max([len(h) for h in histories])
    return envelope_from_histories(histories, envelope_len)


def is_inside_envelope(history, envelope, ignore_first_n_iters=0):
    if len(history) <= ignore_first_n_iters:
        return True

    min_val = min(history)
    cur_iter = len(history) - 1
    if cur_iter >= len(envelope):
        cur_iter = len(envelope) - 1
    return min_val < envelope[cur_iter]


class EnvelopeEarlyTerminate(EarlyTerminate):
    def __init__(self, fraction=0.3, min_runs=3, start_iter=3):
        self.fraction = fraction
        self.min_runs = min_runs
        self.start_iter = start_iter

    @classmethod
    def init_from_config(cls, config):
        pass

    def stop_runs(self, sweep_config, runs):
        info = {}
        terminate_run_names = []
        self._load_metric_name_and_goal(sweep_config)

        complete_run_histories = []
        complete_run_metrics = []
        for run in runs:
            if run.state == "finished":  # complete run
                history = self._load_run_metric_history(run)
                if len(history) > 0:
                    complete_run_histories.append(history)
                    complete_run_metrics.append(min(history))

        complete_runs_count = len(complete_run_histories)
        if complete_runs_count < self.min_runs:
            return [], info

        n = max(int(np.ceil(complete_runs_count * self.fraction)), self.min_runs)

        envelope = envelope_from_top_n(
            complete_run_histories, complete_run_metrics, n)

        for run in runs:
            if run.state == "running":
                history = self._load_run_metric_history(run)

                if not is_inside_envelope(history, envelope,
                                          ignore_first_n_iters=self.start_iter):
                    terminate_run_names.append(run.name)
        return terminate_run_names, info
