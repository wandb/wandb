"""
Sweep service
"""

import itertools
import random
import numpy as np
import math
import scipy.stats as stats
from . import grid_search, bayes_search, random_search
from . import hyperband_stopping, envelope_stopping
from .base import Search


class Sweeps(Search):
    @staticmethod
    def to_class(config):
        method = config.get('method')
        if method is None:
            raise ValueError('config missing required "method" field.')
        method = method.lower()
        if method == 'grid':
            return grid_search.GridSearch()
        elif method == 'bayes':
            return bayes_search.BayesianSearch()
        elif method == 'random':
            return random_search.RandomSearch()
        raise ValueError('method "%s" is not supported' % config['method'])

    def _load_early_terminate_from_config(self, sweep_config):
        if not 'early_terminate' in sweep_config:
            return None

        et_config = sweep_config['early_terminate']
        if not 'type' in et_config:
            raise ValueError("Didn't specify early terminate type")

        if et_config['type'] == 'envelope':
            kw_args = {}
            if 'fraction' in et_config:
                kw_args['fraction'] = et_config['fraction']
            if 'min_runs' in et_config:
                kw_args['min_runs'] = et_config['min_runs']
            if 'start_iter' in et_config:
                kw_args['start_iter'] = et_config['start_iter']

            return envelope_stopping.EnvelopeEarlyTerminate(**kw_args)
        elif et_config['type'] == 'hyperband':
            # one way of defining hyperband, with max_iter, s and possibly eta
            if 'max_iter' in et_config:
                max_iter = et_config['max_iter']
                eta = 3
                if 'eta' in et_config:
                    eta = et_config['eta']

                s = 0
                if 's' in et_config:
                    s = et_config['s']
                else:
                    raise "Must define s for hyperband algorithm if max_iter is defined"

                return hyperband_stopping.HyperbandEarlyTerminate.init_from_max_iter(max_iter, eta, s)
            # another way of defining hyperband with min_iter and possibly eta
            if 'min_iter' in et_config:
                min_iter = et_config['min_iter']
                eta = 3
                if 'eta' in et_config:
                    eta = et_config['eta']
                return hyperband_stopping.HyperbandEarlyTerminate.init_from_min_iter(min_iter, eta)
        else:
            raise 'unsupported early termination type %s'.format(
                et_config['type'])
