"""
Hyperband Early Terminate
"""

import itertools
import random
import numpy as np
import math
import scipy.stats as stats
from .base import EarlyTerminate


class HyperbandEarlyTerminate(EarlyTerminate):
    """
    Implementation of the Hyperband algorithm from
      Hyperband: A Novel Bandit-Based Approach to Hyperparameter Optimization
      https://arxiv.org/pdf/1603.06560.pdf

    Arguments
    bands - Array of iterations to potentially early terminate algorithms
    r - float in [0, 1] - fraction of runs to allow to pass through a band
        r=1 means let all runs through and r=0 means let no runs through
    """
    def __init__(self, bands, r):
        if len(bands) < 1:
            raise "Bands must be an array of length at least 1"
        if r < 0 or r > 1:
            raise "r must be a float between 0 and 1"

        self.bands = bands
        self.r = r

    @classmethod
    def init_from_max_iter(cls, max_iter, eta, s):
        band = max_iter
        bands = []
        for i in range(s):
            band /= eta
            if band < 1:
                break

            bands.append(int(band))

        return cls(sorted(bands), 1.0/eta)


    @classmethod
    def init_from_min_iter(cls, min_iter, eta):
        if eta <= 1:
            raise "eta must be greater than 1"
        if min_iter < 1:
            raise "min_iter must be at least 1"

        band = min_iter
        bands = []
        for i in range(100):
            bands.append(int(band))
            band *= eta

        return cls(bands, 1.0/eta)

    def stop_runs(self, sweep_config, runs):
        terminate_run_names = []
        self._load_metric_name_and_goal(sweep_config)

        all_run_histories = []  # we're going to look at every run
        for run in runs:
            #if run.state == "finished":  # complete run
            history = self._load_run_metric_history(run)
            if len(history) > 0:
                all_run_histories.append(history)

        self.thresholds = []
        # iterate over the histories at every band and find the threshold for a run to be in the top r percentile
        for band in self.bands:
            # values of metric at iteration number "band"
            band_values = [h[band] for h in all_run_histories if len(h) > band]

            if len(band_values) == 0:
                threshold = np.inf
            else:
                threshold = sorted(band_values)[int((self.r) * len(band_values))]

            self.thresholds.append(threshold)


        for run in runs:
            if run.state == "running":
                history = self._load_run_metric_history(run)

                closest_band = -1
                closest_threshold = 0
                for band, threshold in zip(self.bands, self.thresholds):
                    if band < len(history):
                        closest_band = band
                        closest_threshold = threshold
                    else:
                        break

                if closest_band == -1: # no bands apply yet
                    break
                else:
                    if min(history) > closest_threshold:
                        terminate_run_names.append(run.name)


        return terminate_run_names
