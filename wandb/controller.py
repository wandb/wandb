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
from .sweeps.sweeps import Sweeps


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
    categories = ('running', 'finished', 'crashed', 'failed', 'unknown')
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
        self._api = api
        self._sweep_id = sweep_id
        specs = '{"keys": ["_step", "val_loss"], "samples": 100000}'
        specs_json = json.loads(specs)
        sweep = api.sweep(sweep_id, specs)
        if sweep is None:
            raise SweepError("Can not find sweep: %s", sweepid)
        self._sweep_obj = sweep
        self._laststatus = None
        self._logged = 0
        self._verbose = verbose

    #@classmethod
    #def create(cls, args=None):
    #    log("Create sweep")
    #    # TODO(jhr): implement me
    #    c = cls(sweep)
    #    return c

    #@classmethod
    #def find(cls, sweepid, args=None):
    #    inst = cls(sweep, api=api)
    #    inst.args = args
    #    return inst

    def log(self, key, value):
        if not self._verbose:
            return
        line = "# %-10s %s" % (key + ":", value)
        if len(line) > 120:
            line = line[:120] + ".."
        print(line)
        self._logged += 1

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

    def update(self):
        self.reload()
        obj = self._sweep_obj
        #print("SW-c:", obj.get("controller", "NOTFOUND"))
        #print("SW-s:", obj.get("scheduler", "NOTFOUND"))


        run_dicts = obj['runs']
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

        # find completed runs
        # TODO(jhr): crashed runs are hard?
        scheduler = obj.get('scheduler', "{}")
        if scheduler is None:
            scheduler = "{}"
        scheduler = json.loads(scheduler)
        #print("SSSS", scheduler)
        schedlist = scheduler.get('scheduled', [])
        # why is this null? really thought it should be an empty list
        if schedlist is None:
            schedlist = []

        done = []
        for s in schedlist:
            #print("SSS", s)
            r = rmap.get(s['runid'])
            if r:
                #print("RRR", r)
                st = r['state']
                if st == 'running':
                    continue
                #print("CLEAN", r)
                done.append(s['id'])

        controller = obj.get('controller')
        controller = json.loads(controller)
        newclist = []
        clist = controller.get('schedule', [])
        for c in clist:
            if c['id'] not in done:
                newclist.append(c)
        controller['schedule'] = newclist
        controller = json.dumps(controller)
        obj['controller'] = controller
        # NOTE: we arent saving it here
        obj['_runs'] = runs

    def reload(self):
        obj = self._sweep_obj
        sweepid = obj['name']
        specs = '{"keys": ["_step", "val_loss"], "samples": 100000}'
        specs_json = json.loads(specs)
        sweep = self._api.sweep(sweepid, specs)
        self._sweep_obj = sweep

    def reset(self):
        obj = self._sweep_obj
        conf = obj['config']
        conf = yaml.safe_load(conf)
        controller = {}
        controller = json.dumps(controller)
        x = self._api.upsert_sweep(conf, controller=controller, obj_id=obj['id'])
        #print("RRR", x)
        self.reload()

    def schedule(self):
        obj = self._sweep_obj

        config = obj.copy()
        config['runs'] = config['_runs']
        conf = config['config']
        conf = yaml.safe_load(conf)
        #print("CCC", conf, type(conf))
        config['config'] = conf
        #print("DDDDD", config)
        search = Sweeps.to_class(conf)
        next_run = search.next_run(config)
        #print("NNNN", next_run)
        endsweep = False
        if next_run:
            next_run, info = next_run
            if info:
                #print("DEBUG", info)
                pass
        else:
            endsweep = True
            #print("END OF SWEEP?")
        stop_runs = search.stop_runs(config)
        #stop_runs = ['fdfsddds']
        if next_run or endsweep:
            old_controller = obj['controller']
            if old_controller:
                old_controller = json.loads(old_controller)
                schedule = old_controller.get("schedule")
                if schedule:
                    # TODO(jhr): check to see if we already have something scheduled
                    return

            if not endsweep:
                #nr = json.loads(next_run)
                nr = next_run
                #print("NR", nr)
                nr = ','.join(['%s=%s' % (d[0], d[1]['value']) for d in nr.items()])
                self.log("Scheduling", nr)
            #controller = '{"hello": 1}'
            #controller = json.loads(controller)
            #print("old control", old_controller)
            #print("next", next_run)
            schedule_list = []
            schedule_id = id_generator()
            schedule_list.append({'id': schedule_id, 'data': {'args': next_run}})
            controller = {"schedule": schedule_list}
            controller = json.dumps(controller)
            #print("ADD: ", controller)
            x = self._api.upsert_sweep(conf, controller=controller, obj_id=obj['id'])
            #print("RESP: ", x)

        for r in stop_runs:
            self.log("Stopping", r)
            controller = {}
            controller['earlystop'] = [r]
            controller = json.dumps(controller)
            x = self._api.upsert_sweep(conf, controller=controller, obj_id=obj['id'])
            #print("RESP: ", x)

        return endsweep


    def controller(self):
        #log("Controller")
        done = False
        while not done:
            self.status()
            self.update()
            done = self.schedule()
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
    sweep = Sweep(api, sweep_id=sweep_id, verbose=verbose)
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
    search = Sweeps.to_class(config)
    try:
        next_run = search.next_run(sweep)
    except Exception as err:
        return str(err)
