"""
Sweep service
"""

import itertools
import random
import numpy as np
import math
from wandb.sweeps import grid_search, bayes_search, random_search
from wandb.sweeps import raytune
from wandb.sweeps import hyperband_stopping, envelope_stopping
from wandb.sweeps import base


class Search(base.Search):
    @staticmethod
    def to_class(config):
        if config.get('tune'):
            return raytune.RayTuneSearch()
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


class EarlyTerminate(base.EarlyTerminate):
    @staticmethod
    def to_class(config):
        et_config = config.get('early_terminate')
        if not et_config:
            return base.EarlyTerminate()
        et_type = et_config.get('type')
        if not et_type:
            raise ValueError("Didn't specify early terminate type")
        et_type = et_type.lower()
        if et_type == 'envelope':
            return envelope_stopping.EnvelopeEarlyTerminate.init_from_config(et_config)
        elif et_type == 'hyperband':
            return hyperband_stopping.HyperbandEarlyTerminate.init_from_config(et_config)
        raise ValueError(
            'unsupported early termination type %s' % et_type)
