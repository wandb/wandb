# -*- coding: utf-8 -*-
"""Sweep controller API.

This module implements the sweep API

Example:
    import wandb
    api = wandb.Api()
    tuner = api.controller()
"""
from __future__ import print_function

import yaml
import json
import time
import string

import wandb
from wandb.apis import InternalApi
from wandb.util import get_module

wandb_sweeps = get_module("wandb.sweeps.sweeps")


class _Run(object):
    """Run object containing attributes about a run for sweep searching and stopping."""
    def __init__(self, name, state, history, config, summaryMetrics, stopped):
        self.name = name
        self.state = state
        self.config = config
        self.history = history
        self.summaryMetrics = summaryMetrics
        self.stopped = stopped

    def __repr__(self):
        return 'Run(%s,%s,%s,%s,%s,%s)' % (self.name, self.state, self.config, self.history, self.summaryMetrics, self.stopped)

    @classmethod
    def init_from_dict(cls, run_dict):
        """Initialize from dictionary.
    
        Args:
            run_dict (dict): Run dictionaries with keys 'name', 'state', 'config', 'stopped', 'sampledHistory', 'summaryMetrics', ...
        Returns:
            _Run(): Run object
        """
        name = run_dict['name']
        state = run_dict['state']
        config = run_dict['config']
        stopped = run_dict['stopped']
        config = json.loads(config)
        history = run_dict['sampledHistory']
        history = history[0]
        summaryMetrics = run_dict['summaryMetrics']
        if summaryMetrics:
            summaryMetrics = json.loads(summaryMetrics)
        r = cls(name, state, history, config, summaryMetrics, stopped)
        return r


class _WandbController():
    def __init__(self, sweep_id_or_config=None):
        # sweep id configured in constuctor
        self._sweep_id = None

        # The following are updated every sweep step
        # raw sweep object (dict of strings)
        self._sweep_obj = None
        # parsed sweep config (dict)
        self._sweep_config = None
        # sweep metric used to optimize (str or None)
        self._sweep_metric = None
        # list of _Run objects
        self._sweep_runs = None
        # dictionary mapping name of run to run object
        self._sweep_runs_map = None
        # scheduler dict (read only from controller) - used as feedback from the server
        self._scheduler = None
        # controller dict (write only from controller) - used to send commands to server
        self._controller = None
        # keep track of controller dict from previous step
        self._controller_prev_step = None

        self._api = InternalApi()

        print("sweep", sweep_id_or_config)
        if isinstance(sweep_id_or_config, str):
            self._sweep_id = sweep_id_or_config
        elif isinstance(sweep_id_or_config, dict):
            pass
        else:
            # TODO: error
            print("ERROR: type")
            return
        sweep_obj = self._sweep_object_update_from_backend()
        if sweep_obj is None:
            # TODO: error
            print("ERROR: no sweep", self._sweep_id)
            #raise SweepError("Can not find sweep: %s" % sweep_id_or_config)
            return
        self._sweep_obj = sweep_obj
        print("GOTSWEEP", sweep_obj)

    def configure_search(self, search):
        pass
    
    def configure_stopping(self, stopping):
        pass

    def configure_metric(self, metric, goal=None):
        pass

    def configure_parameters_add(self, name, values=None, value=None):
        pass

    def run(self):
        while not self.done():
            self.step()
            time.sleep(5)

    def _sweep_object_update_from_backend(self):
        specs_json = {}
        if self._sweep_metric:
            k = ["_step"]
            k.append(self._sweep_metric)
            specs_json = {"keys": k, "samples": 100000}
        specs = json.dumps(specs_json)
        # FIXME(jhr): catch exceptions?
        sweep_obj = self._api.sweep(self._sweep_id, specs)
        if not sweep_obj:
            return
        self._sweep_obj = sweep_obj
        self._sweep_config = yaml.safe_load(sweep_obj['config'])
        self._sweep_metric = self._sweep_config.get('metric', {}).get('name')
        self._sweep_runs = [_Run.init_from_dict(r) for r in sweep_obj['runs']]
        self._sweep_runs_map = {r['name']: r for r in self._sweep_runs}

        self._controller = json.loads(sweep_obj.get('controller') or '{}')
        self._scheduler = json.loads(sweep_obj.get('scheduler') or '{}')
        self._controller_prev_step = self._controller.copy()
        return sweep_obj

    def step(self):
        self._sweep_object_update_from_backend()
        params = self.search()
        if params:
            self.schedule(params)

    def done(self):
        if self._sweep_obj.get('state') == 'RUNNING':
            return False
        return True

    def _search(self):
        sweep = self._sweep_obj.copy()
        sweep['runs'] = self._sweep_runs
        sweep['config'] = self._sweep_config
        search = wandb_sweeps.Search.to_class(self._sweep_config)
        next_run = search.next_run(sweep)
        print("NEXT", next_run)
        endsweep = False
        if next_run:
            next_run, info = next_run
            if info:
                #print("DEBUG", info)
                pass
        else:
            endsweep = True
        return next_run

    def search(self):
        params = self._search()
        return params

    def schedule(self, params):
        print("SCHEDULE", params)

    def print_status(self):
        print("STATUS", self._sweep_obj)

    def print_space(self):
        pass

    def print_summary(self):
        pass


def controller(sweep_id_or_config=None):
    c = _WandbController(sweep_id_or_config)
    return c
