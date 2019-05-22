# TODO(jhr): yaml config: controller:  type: local
# TODO(jhr): add method to get advanced info from "method" and "early_terminate"
# TODO(jhr): can we get which parts are variable from next_args
# TODO(jhr): add controller json field to sweep object: controller: { scheduler: x },  host protection, last update, allow modification on upsert,
# TODO(jhr): need actions json field
# TODO(jhr): get summaries and histories for runs
# TODO(jhr): optimize to only get summaries, histories when changed
# TODO(jhr): log more run changes
# TODO(jhr): tunables (line length, update frequency, status frequency, debug level, number of outputs per update)

# TODO(jhr): alert for missing libraries scikit etc
# TODO(jhr): alert for older python version (or migrate code to older print strings)

from __future__ import print_function
import wandb
from wandb.util import get_module
from wandb.apis import InternalApi
import logging
import yaml
import time
import json
import random
import string
#from wandb.sweeps.sweeps import Search, EarlyTerminate
import sys
import six


wandb_sweeps = None
if sys.version_info >= (3, 6, 0):
    wandb_sweeps = get_module("wandb.sweeps.sweeps")


logger = logging.getLogger(__name__)


# Name:           run.Name,
# Config:         json.RawMessage(config),
# History:        json.RawMessage(history),
# State:          state,
# SummaryMetrics: json.RawMessage(summary),
class Run(object):
    def __init__(self, name, state, history, config, summaryMetrics, stopped):
        self.name = name
        self.state = state
        self.config = config
        self.history = history
        self.summaryMetrics = summaryMetrics
        self.stopped = stopped

    def __repr__(self):
        return 'Run(%s,%s,%s,%s,%s)' % (self.name, self.state, self.config, self.history, self.summaryMetrics)


def id_generator(size=10, chars=string.ascii_lowercase + string.digits):
    return ''.join(random.choice(chars) for _ in range(size))


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
        self._sweep_sched_map = {}
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
        # FIXME(jhr): catch exceptions?
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
            rmap[name] = n
        self._sweep_runs = runs
        self._sweep_runs_dict = rmap
        self._sweep_obj = sweep
        self._sweep_obj_id = sweep['id']

    def save(self, controller):
        controller = json.dumps(controller)
        self._api.upsert_sweep(
            self._config, controller=controller, obj_id=self._sweep_obj_id)
        # FIXME(jhr): check return? catch exceptions?
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
                self._sweep_sched_map[s['id']] = s['runid']
                st = r.state
                if r.stopped:
                    stopped_runs.append(s['runid'])
                # TODO(jhr): check to see if we have a result
                sm = r.summaryMetrics
                # if no metrics yet and running dont count this as done (not really done, more like started)
                if not sm and st == 'running':
                    #print("Not started", s['runid'])
                    continue
                #print("Started", s['runid'], sm)
                #if st == 'running':
                #    continue
                #print("CLEAN", r)
                done_ids.append(s['id'])
                done_runs.append(s['runid'])
                # track started runs? #TODO

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
            #print("CONTROLLER", self._controller)
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

    def schedule_generic(self, next_run, schedule_id=None, stop_runs=None):
        schedule_list = self._controller.get('schedule', [])
        #schedule_list = []
        if not schedule_id:
            schedule_id = id_generator()
        schedule_list.append(
            {'id': schedule_id, 'data': {'args': next_run}})
        self._controller["schedule"] = schedule_list

    # break this function up so it can be used by other uses
    def schedule_wandb(self):
        sweep = self._sweep_obj.copy()
        sweep['runs'] = self._sweep_runs
        sweep['config'] = self._config
        search = wandb_sweeps.Search.to_class(self._config)
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
        stopper = wandb_sweeps.EarlyTerminate.to_class(self._config)
        stop_runs, info = stopper.stop_runs(self._config, sweep['runs'])
        debug_lines = info.get('lines', [])
        if self._verbose and debug_lines:
            for l in debug_lines:
                self.logline("# " + l)

        if stop_runs:
            # TODO(jhr): check previous stopped runs
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
                    # print("....")
                    return

            if not endsweep:
                #nr = json.loads(next_run)
                nr = next_run
                #print("NR", nr)
                nr = ', '.join(['%s = %s' % (d[0], d[1]['value'])
                                for d in nr.items()])
                self.log("Scheduling", nr)
            #controller = '{"hello": 1}'
            #controller = json.loads(controller)
            #print("old control", old_controller)
            #print("next", next_run)
            schedule_list = []
            schedule_id = id_generator()
            schedule_list.append(
                {'id': schedule_id, 'data': {'args': next_run}})
            self._controller["schedule"] = schedule_list
            #print("ADD: ", controller)
            #print("RESP: ", x)
        return endsweep

    def controller(self):
        # log("Controller")
        done = False
        while not done:
            self.status()
            self.prepare()
            done = self.schedule_wandb()
            self.update()
            time.sleep(self.delay)
        self.status()

    def run(self):
        self.reset()
        self.controller()


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
    search = wandb_sweeps.Search.to_class(config)
    try:
        next_run = search.next_run(sweep)
    except Exception as err:
        return str(err)
    try:
        stopper = wandb_sweeps.EarlyTerminate.to_class(config)
        runs = stopper.stop_runs(config, [])
    except Exception as err:
        return str(err)


class SweepController(object):
    def __init__(self, prog):
        self._running = 0
        self._available = 12
        self._sweep = None
        self._laststep = {}
        self._prog = prog

    def create(self):
        """Create a sweep."""
        config = {'controller': {'type': 'local'}, 'program': self._prog, 'metric': {'name': 'neg_mean_loss'}}
        api = InternalApi()
        #print("c1")
        sweep_id = api.upsert_sweep(config)
        #print("c2")
        print('Create sweep with ID:', sweep_id)
        verbose = True
        try:
            sweep = Sweep(api, sweep_id=sweep_id, verbose=verbose)
        except SweepError as err:
            fail
        sweep.reset()

        sweep.status()
        sweep.prepare()
        #done = self.schedule()
        #sweep.update()
        self._sweep = sweep


    def should_schedule(self):
        """Should this task be scheduled?"""
        r = False
        #print("WANDB_SHOULD1", r, self._running, self._available)
        if self._running < self._available:
            return True
        #print("WANDB_SHOULD", r)
        return r

    def schedule(self, x, id=None):
        """Schedule a task."""
        self._running += 1
        #print("WANDB_SCHEDULE", x, x.config, self._running)
        # TODO: Add to scheduler, upsert
        self._sweep.status()
        self._sweep.prepare()
        d = {}
        for k,v in six.iteritems(x.config):
            d.setdefault(k, {})
            d[k]['value'] = v
        d.setdefault('_wandb_tune_run', {})
        d['_wandb_tune_run']['value'] = True
        self._sweep.schedule_generic(d, schedule_id=id)
        self._sweep.update()
        r = None
        return r

    def set_resources(self, c):
        """Configure how many resources are available."""
        #print("setavail", c)
        self._available = c

    def stop_trial(self, c):
        #print("got trial to stop:", c)
        self._running -= 1
        return

    def get_id(self, trial):
        #print("JHR REMOTEGET:", trial)
        remote = "JHRrem" + id_generator()
        return remote

    # _process_events -> get_next_available_trial  TODO: make blocking
    def wait(self, object_ids):

        # TODO(JHR): poll object_ids waiting for an update?
        # if we are too early and return a ready_id before it is ready
        # we will fail when checking should_stop
        # how do we know we got a change?  keep a dict of previous results

        # TODO(JHR): how do i map from tune objectids, to runids?
        # summaryMetrics
        # _sweep_sched_map is the annswer for now

        #print("WANDB_WAIT", object_ids)
        #result_id = sorted(object_ids)[0]


        #print("JHRWAIT")
        ready = None
        while not ready:
            time.sleep(0.5)
            self._sweep.status()
            self._sweep.prepare()
            #done = self.schedule()
            self._sweep.update()

            sched_map = self._sweep._sweep_sched_map
            sched_inv = dict([[v,k] for k,v in six.iteritems(sched_map)])
            #print("WANDB_WAIT SCHED", sched_map)

            runs = self._sweep._sweep_runs
            #print("##################### JHRrd", runs)
            # if rd or rd changed?
            if runs:
                for r in runs:
                    o = r.summaryMetrics
                    if not o:
                        continue
                    if r.name not in sched_inv:
                        continue
                    obj_id = sched_inv[r.name]
                    if obj_id not in object_ids:
                        continue
                    # make sure we set the right readyid
                    # check if changed
                    s = o.get('_step')
                    #print("we got", r, o, s, self._laststep)
                    ls = self._laststep.get(r.name)
                    if s != ls:
                        ready = r.name
                        self._laststep[r.name] = s
                        break
                    if r.state != 'running':
                        #FIXME: hack to prevent hanging in wait
                        ready = r.name
                        break
            # move sleep to start to avoid pegging cpu, or seperate sweep
            if not ready:
                time.sleep(self._sweep.delay)

        #result_id = object_ids[0]
        #ready_ids = [result_id]
        result_id = sched_inv[ready]
        ready_ids = [result_id]

        return ready_ids, []

    def get(self, trial_name):
        #print("GETGET")
        #print("GOTTRIAL", trial_name)
        result = {}
        runs = self._sweep._sweep_runs
        sched_map = self._sweep._sweep_sched_map
        runid = sched_map[trial_name]
        r = None
        for run in runs:
            if run.name == runid:
                r = run
                break
        # TODO check for no matching run
        for k, v in six.iteritems(r.summaryMetrics):
            result[k] = v
        #print("get:", result)
        result['time_this_iter_s'] = 0.5
        result['time_total_s'] = 0.9
        result['training_iteration'] = 2
        if r.state != "running":
            result['done'] = True
        return result

    def run(self):
        pass
