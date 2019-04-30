from __future__ import print_function
#import collections
#import json
import logging
#import multiprocessing
#import os
#import socket
#import subprocess
#import sys
#import traceback
#import time
#
#import six
#
#import wandb
from wandb.apis import InternalApi
#from wandb.wandb_config import Config
#from wandb import util
#from wandb import wandb_run


logger = logging.getLogger(__name__)


"""Sweep manager.

Usage:
    sweep.py create <file.yaml>
    sweep.py controller <file.yaml>
    sweep.py controller <sweep>

Options:
    -h --help     Show this screen.
    --version     Show version.
"""

# TODO(jhr): yaml config: controller:  type: local
# TODO(jhr): add method to get advanced info from "method" and "early_terminate"
# TODO(jhr): can we get which parts are variable from next_args
# TODO(jhr): add controller json field to sweep object: controller: { scheduler: x },  host protection, last update, allow modification on upsert,
# TODO(jhr): need actions json field
# TODO(jhr): get summaries and histories for runs
# TODO(jhr): optimize to only get summaries, histories when changed
# TODO(jhr): log more run changes
# TODO(jhr): tunables (line length, update frequency, status frequency, debug level, number of outputs per update)



import argparse
import pickle
import wandb
import numpy as np
import yaml
import time
import sys
import json
import random
import string

from wandb.apis import internal
from .sweeps.sweeps import Search, EarlyTerminate


#api = wandb.Api()

# Name:           run.Name,
# Config:         json.RawMessage(config),
# History:        json.RawMessage(history),
# State:          state,
# SummaryMetrics: json.RawMessage(summary),

class Run(object):
    def __init__(self, name, state, history, config, summaryMetrics):
        self.name = name
        self.state = state
        self.config = config
        self.history = history
        self.summaryMetrics = summaryMetrics

    def __repr__(self):
        return 'Run(%s,%s,%s,%s,%s)' % (self.name, self.state, self.config, self.history, self.summaryMetrics)


def id_generator(size=10, chars=string.ascii_lowercase + string.digits):
    return ''.join(random.choice(chars) for _ in range(size))

def getsweep(user, proj, sw, max_search=None, max_get=None):
    """xxx"""
    fn = '%s__%s__%s.pkl' % (user, proj, sw)
    try:
        with open(fn, "rb") as fp:
            return pickle.load(fp)
    except FileNotFoundError:
        pass
        
    runs = api.runs("%s/%s" % (user, proj))
    ret = {}
    num = 0
    found = 0
    for r in runs:
        print("Run: %d.....    \r" % num, end='')
        num += 1
        #print(r.client, r.project, r.username, r.name, r.dir, r.state, r._summary, 'sweep:', r.sweep)
        sname = None
        s = r.sweep
        if max_search and num > max_search:
            break
        if s:
            sname = s.get('name')
            sconf = s.get('config')
        if sname != sw:
            continue
        print(r.name, sname)
        ret['name'] = sname
        ret['config'] = sconf
        h = r.history(pandas=False)
        run = {}
        run['name'] = r.name
        run['history'] = h
        run['state'] = r.state
        run['config'] = r.config
        run['shouldStop'] = r.shouldStop
        run['stopped'] = r.stopped
        run['running'] = r.running
        run['failed'] = r.failed
        #print("run", run)
        ret.setdefault('runs',[]).append(run)
        found += 1
        if max_get and found > max_get:
            break
    print("done.          ")
    with open(fn, "wb") as fp:
        pickle.dump(ret,fp)
    return ret


def showsweeps(sweep):
    import matplotlib.pyplot as plt
    import matplotlib.tri as tri
    data = []

    cfg = None
    try:
        cfg = yaml.load(sweep.get('config'))
    except yaml.YAMLError as exc:
        print(exc)
        return

    print("CONFIG", cfg)
    targ = cfg.get("metric").get("name")
    print("target", targ)
    #targ = "accuracy_top_5"
    params = cfg.get("parameters")
    axis = []
    for k, v in params.items():
        vals = v.get("values")
        if vals and type(vals) is type([]) and len(vals) > 1:
            axis.append(k)
        if v.get("distribution"):
            axis.append(k)

    print("axis:", axis)
    axis = axis[:2]
    #axis = ("train.batch_size", "optimizer.args.lr")

    xmax = None
    ymax = None
    xmin = None
    ymin = None
    bad = []
    for r in sweep.get('runs'):
        c = r.get('config')
        hc = c.copy()

        x, y = c.get(axis[0]), c.get(axis[1])
        if x is not None:
            xmin = min(xmin, x) if xmin is not None else x
            xmax = max(xmax, x) if xmax is not None else x
        if y is not None:
            ymin = min(ymin, y) if ymin is not None else y
            ymax = max(ymax, y) if ymax is not None else y
        if r.get("state") in ("failed", "crashed"):
            bad.append((x, y, 0))

        point = None
        for h in r.get('history'):
            if targ not in h:
                continue
            point=(c[axis[0]], c[axis[1]], h[targ])
        if point:
            data.append(point)
        print(r.get('name'), r.get('state'), r.get('stopped'), r.get('shouldStop'), x, y, point)

    print("points", data)
    x, y, z = [list(t) for t in zip(*data)]

    if bad:
        bx, by, _ = [list(t) for t in zip(*bad)]

    ngridx = 100
    ngridy = 200
    print('xmax', xmax)
    print('ymax', ymax)
    xi = np.linspace(xmin, xmax, ngridx)
    yi = np.linspace(ymin, ymax, ngridy)
    triang = tri.Triangulation(x, y)
    interpolator = tri.LinearTriInterpolator(triang, z)
    Xi, Yi = np.meshgrid(xi, yi)
    zi = interpolator(Xi, Yi)
        
    print("config", sweep.get('config'))
    # train.batch_size optimizer.args.lr
    # accuracy_top_5
    #xlist = np.linspace(-3.0, 3.0, 100)
    #ylist = np.linspace(-3.0, 3.0, 100)
    #X, Y = np.meshgrid(xlist, ylist)
    #Z = np.sqrt(X**2 + Y**2)
    plt.figure()
    cp = plt.contourf(xi, yi, zi)
    if bad:
        l2 = plt.plot(bx,by,'ko', ms=3)
        plt.setp(l2, markersize=5)
        plt.setp(l2, markerfacecolor='C5')
    l = plt.plot(x,y,'ko', ms=3)
    plt.setp(l, markersize=10)
    plt.setp(l, markerfacecolor='C0')

    plt.colorbar(cp)
    plt.title(targ)
    plt.xlabel(axis[0])
    plt.ylabel(axis[1])
    plt.show()
    # https://matplotlib.org/gallery/images_contours_and_fields/irregulardatagrid.html


def log(s):
    print("INFO: %s" % s)



def get_run_metrics(runs):
    metrics = {}
    categories = ('running', 'finished', 'crashed', 'failed')
    for r in runs:
        state = r['state']
        found = 'unknown'
        for c in categories:
            if state == c:
                found = c
                break
        metrics.setdefault(found, 0)
        metrics[found] += 1
    return metrics


def metrics_status(metrics):
    categories = ('finished', 'crashed', 'failed', 'unknown', 'running')
    mlist = []
    for c in categories:
        if not metrics.get(c):
            continue
        mlist.append("%s: %d" % (c.capitalize(), metrics[c]))
    s = ', '.join(mlist)
    return s


class SweepError(Exception):
    """Base class for sweep errors"""
    pass


class Sweep(object):
    delay = 5

    def __init__(self, api, sweep_id, verbose=False):
        self._laststatus = None
        self._logged = 0
        self._verbose = verbose
        self._api = api
        self._sweep_id = sweep_id
        self._scheduler = {}
        self._controller = {}
        self._controller_last = {}
        sweep_obj = api.sweep(sweep_id, '{}')
        if sweep_obj is None:
            raise SweepError("Can not find sweep: %s" % sweep_id)
        self._config = yaml.safe_load(sweep_obj['config'])
        self._sweep_obj = sweep_obj
        self._sweep_obj_id = sweep_obj['id']
        self._sweep_runs = []
        self._sweep_runs_dict = {}
        #print("INIT: ", self._sweep_obj)

    def logline(self, line):
        if not self._verbose:
            return
        if len(line) > 120:
            line = line[:120] + ".."
        print(line)
        self._logged += 1

    def log(self, key, value):
        line = "# %-10s %s" % (key + ":", value)
        self.logline(line)

    def reload(self):
        k = ["_step"]
        metric = self._config.get("metric", {}).get("name")
        if metric:
            k.append(metric)
        specs_json = {"keys": k, "samples": 100000}
        specs = json.dumps(specs_json)
        #FIXME(jhr): catch exceptions?
        sweep = self._api.sweep(self._sweep_id, specs)
        controller = sweep.get('controller')
        controller = json.loads(controller)
        self._controller = controller
        self._controller_last = controller.copy()
        scheduler = sweep.get('scheduler', "{}")
        if scheduler is None:
            scheduler = "{}"
        scheduler = json.loads(scheduler)
        self._scheduler = scheduler

        run_dicts = sweep['runs']
        runs = []
        rmap = {}
        for r in run_dicts:
            #print("GOT:", r)
            name = r['name']
            state = r['state']
            config = r['config']
            config = json.loads(config)
            history = r['sampledHistory']
            history = history[0]
            summaryMetrics = r['summaryMetrics']
            if summaryMetrics:
                summaryMetrics = json.loads(summaryMetrics)
            # TODO(jhr): build history
            n = Run(name, state, history, config, summaryMetrics)
            runs.append(n)
            rmap[name] = r
        self._sweep_runs = runs
        self._sweep_runs_dict = rmap
        self._sweep_obj = sweep
        self._sweep_obj_id = sweep['id']

    def save(self, controller):
        controller = json.dumps(controller)
        self._api.upsert_sweep(self._config, controller=controller, obj_id=self._sweep_obj_id)
        #FIXME(jhr): check return? catch exceptions?
        self.reload()

    def reset(self):
        self.save({})

    def prepare(self):
        self.reload()
        obj = self._sweep_obj
        #print("SW-c:", obj.get("controller", "NOTFOUND"))
        #print("SW-s:", obj.get("scheduler", "NOTFOUND"))

        # find completed runs
        # TODO(jhr): crashed runs are hard?
        schedlist = self._scheduler.get('scheduled', [])
        # why is this null? really thought it should be an empty list
        if schedlist is None:
            schedlist = []

        done_ids = []
        done_runs = []
        stopped_runs = []
        for s in schedlist:
            #print("SSS", s)
            r = self._sweep_runs_dict.get(s['runid'])
            if r:
                #print("RRR", r)
                st = r['state']
                if r.get('stopped'):
                    stopped_runs.append(s['runid'])
                if st == 'running':
                    continue
                #print("CLEAN", r)
                done_ids.append(s['id'])
                done_runs.append(s['runid'])

        newclist = []
        clist = self._controller.get('schedule', [])
        for c in clist:
            if c['id'] not in done_ids:
                newclist.append(c)
        # NOTE: we arent saving it here
        self._controller['schedule'] = newclist

        # TODO(jhr): Check for stopped runs, if stopped already remove from list
        earlystop = self._controller.get('earlystop', [])
        earlystop_new = []
        for r in earlystop:
            if r not in done_runs and r not in stopped_runs:
                earlystop_new.append(r)
        if earlystop_new:
            self._controller['earlystop'] = earlystop_new
        else:
            self._controller.pop('earlystop', None)

    def update(self):
        if self._controller != self._controller_last:
            self.save(self._controller)

    def status(self):
        # Scheduled: runid (Params:)
        # Starting:  runid (Agent: a)
        # Started:   runid (Agent: a)
        # Running:   runid (X: Y)
        # Stopping:  runid (Agent: a)
        # Stopped:   runid (Agent: a)
        # Failed:    runid (Error?)
        # Finished:  runid (X: Y)
        # Crashed:   runid (Error?)
        sweep = self._sweep_obj['name']
        state = self._sweep_obj['state']
        runs = self._sweep_obj['runs']
        conf = self._sweep_obj['config']
        conf = yaml.safe_load(conf)
        run_count = len(runs)
        metrics = get_run_metrics(runs)
        stopped = len([r for r in runs if r['stopped']])
        stopping = len([r for r in runs if r['shouldStop']])
        stopstr = ""
        if stopped or stopping:
            stopstr = "Stopped: %d" % stopped
            if stopping:
                stopstr += " (Stopping: %d)" % stopping
        #print('junk', runs)
        s = metrics_status(metrics)
        method = conf.get('method', 'unknown')
        stopping = conf.get('early_terminate', None)
        params = []
        params.append(method)
        if stopping:
            params.append(stopping.get('type', 'unknown'))
        params = ','.join(params)
        #print("obj:", self._sweep_obj['runs'])
        sections = []
        sections.append("Sweep: %s (%s)" % (sweep, params))
        #sections.append("State: %s" % (state))
        if s:
            sections.append("Runs: %d (%s)" % (run_count, s))
        else:
            sections.append("Runs: %d" % (run_count))
        if stopstr:
            sections.append(stopstr)
        sections = ' | '.join(sections)

        if self._laststatus != sections or self._logged:
            print(sections)
        self._laststatus = sections
        self._logged = 0

    def schedule(self):
        sweep = self._sweep_obj.copy()
        sweep['runs'] = self._sweep_runs
        sweep['config'] = self._config
        search = Search.to_class(self._config)
        #print("NEXT", sweep)
        next_run = search.next_run(sweep)
        endsweep = False
        if next_run:
            next_run, info = next_run
            if info:
                #print("DEBUG", info)
                pass
        else:
            endsweep = True
        #print("XXXX", endsweep)
        stopper = EarlyTerminate.to_class(self._config)
        stop_runs, info = stopper.stop_runs(self._config, sweep['runs'])
        debug_lines = info.get('lines', [])
        if self._verbose and debug_lines:
            for l in debug_lines:
                self.logline("# " + l)

        if stop_runs:
            #TODO(jhr): check previous stopped runs
            earlystop = self._controller.get('earlystop', []) + stop_runs
            earlystop = list(set(earlystop))
            self.log("Stopping", ','.join(earlystop))
            self._controller['earlystop'] = earlystop

        #stop_runs = ['fdfsddds']
        if next_run or endsweep:
            old_controller = self._controller
            if old_controller:
                schedule = old_controller.get("schedule")
                if schedule:
                    # TODO(jhr): check to see if we already have something scheduled
                    #print("....")
                    return

            if not endsweep:
                #nr = json.loads(next_run)
                nr = next_run
                #print("NR", nr)
                nr = ', '.join(['%s = %s' % (d[0], d[1]['value']) for d in nr.items()])
                self.log("Scheduling", nr)
            #controller = '{"hello": 1}'
            #controller = json.loads(controller)
            #print("old control", old_controller)
            #print("next", next_run)
            schedule_list = []
            schedule_id = id_generator()
            schedule_list.append({'id': schedule_id, 'data': {'args': next_run}})
            self._controller["schedule"] = schedule_list
            #print("ADD: ", controller)
            #print("RESP: ", x)
        return endsweep

    def controller(self):
        #log("Controller")
        done = False
        while not done:
            self.status()
            self.prepare()
            done = self.schedule()
            self.update()
            time.sleep(self.delay)
        self.status()

    def run(self):
        self.reset()
        self.controller()


def simulate(args):
    sweep = getsweep(args.entity, args.project, args.sweep)
    pass


def visualize(args):
    pass
    #showsweeps(sweep)


def usage(s=None):
    u = __doc__.split("Usage:", 1)[-1]
    if not s:
        return u
    print(u)
    print(s)
    sys.exit(1)


def xmain():
    parser = argparse.ArgumentParser(usage=usage(), formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--entity", type=str, help="project name")
    parser.add_argument("--project", type=str, help="project name")
    parser.add_argument("--sweep", type=str, help="sweep name")
    parser.add_argument("command", type=str, choices=("controller", "create", "simulate"), help="sweep command")
    parser.add_argument("params", type=str, nargs="*", help="sweep args")

    args = parser.parse_args()
    if args.command == "create":
        sweep = Sweep.create(args)
        sweep.controller()
    elif args.command == "controller":
        if len(args.params) != 1:
            usage("controller requires 1 argument")
        sweep = Sweep.find(args.sweep, args=args)
        sweep.reset()
        sweep.controller()

    #args, unknown = parser.parse_known_args()
    #print("args", args)
    #user, proj, sw = 'jeffr', 'bad-sweep', 'gho3bmio'
    #user, proj, sw = 'tri', 'sweep_test', '6ygj1md9'
    #user, proj, sw = 'tri', 'monodepth-vitor-sweep','tgy3wshc'
    #sweep = getsweep(user, proj, sw, max_search=5000, max_get=1000)
    #print(sweep)


def run_controller(sweep_id=None, verbose=False):
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    api = InternalApi()
    try:
        sweep = Sweep(api, sweep_id=sweep_id, verbose=verbose)
    except SweepError as err:
        wandb.termerror('Controller Error: %s' % err)
        return
    sweep.run()

def validate(config):
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    sweep = {}
    sweep['config'] = config
    sweep['runs'] = []
    search = Search.to_class(config)
    try:
        next_run = search.next_run(sweep)
    except Exception as err:
        return str(err)
    try:
        stopper = EarlyTerminate.to_class(config)
        runs = stopper.stop_runs(config, [])
    except Exception as err:
        return str(err)
