from __future__ import print_function

import yaml
import json
import time
import string

import wandb
from wandb.apis import InternalApi
from wandb.util import get_module

wandb_sweeps = get_module("wandb.sweeps.sweeps")


class Run(object):
    def __init__(self, name, state, history, config, summaryMetrics, stopped):
        self.name = name
        self.state = state
        self.config = config
        self.history = history
        self.summaryMetrics = summaryMetrics
        self.stopped = stopped

    def __repr__(self):
        return 'Run(%s,%s,%s,%s,%s,%s)' % (self.name, self.state, self.config, self.history, self.summaryMetrics, self.stopped)


def _parse_runs(run_dicts):
        runs = []
        #print("RUNDICTS sweep", sweep)
        #print("RUNDICTS control", run_dicts)
        for r in run_dicts:
            #print("GOT:", r)
            name = r['name']
            state = r['state']
            config = r['config']
            stopped = r['stopped']
            config = json.loads(config)
            history = r['sampledHistory']
            history = history[0]
            summaryMetrics = r['summaryMetrics']
            if summaryMetrics:
                summaryMetrics = json.loads(summaryMetrics)
            # TODO(jhr): build history
            n = Run(name, state, history, config, summaryMetrics, stopped)
            runs.append(n)
        return runs


class WandbController():
    def __init__(self, sweep_id_or_config=None):
        self._sweep_id = None
        self._sweep_obj = None
        self._sweep_config = None
        self._sweep_metric = None
        self._sweep_runs = None
        self._sweep_runs_map = None

        print("sweep", sweep_id_or_config)
        if isinstance(sweep_id_or_config, str):
            self._sweep_id = sweep_id_or_config
        elif isinstance(sweep_id_or_config, dict):
            pass
        else:
            # TODO: error
            print("ERROR: type")
            return
        self._api = InternalApi()
        sweep_obj = self._load()
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

    def _load(self):
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
        self._sweep_runs = _parse_runs(sweep_obj['runs'])
        self._sweep_runs_map = {r['name']: r for r in self._sweep_runs}

        self._controller = json.loads(sweep_obj.get('controller') or '{}')
        self._scheduler = json.loads(sweep_obj.get('scheduler') or '{}')
        # keep track of old controller object to determine if an update is needed
        self._controller_last = self._controller.copy()
        return sweep_obj

    def step(self):
        self._load()
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
    c = WandbController(sweep_id_or_config)
    return c
