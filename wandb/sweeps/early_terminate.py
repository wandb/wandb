"""
Library to help with early termination of runs
Here we use a strategy where we take the top k runs or top k percent of runs
and then we build up an envelope where we stop jobs where the metric doesn't get better
"""
import numpy as np


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
