# -*- coding: utf-8 -*-
"""Sweep controller.

This module implements the sweep controller.

On error an exception is raised:
    ControllerError

Example:
    import wandb

    #
    # create a sweep controller
    #

    # There are three different ways sweeps can be created:
    # (1) create with sweep id from `wandb sweep` command
    sweep_id = 'xyzxyz2'
    tuner = wandb.controller(sweep_id)
    # (2) create with sweep config
    sweep_config = {}
    tuner = wandb.controller()
    tuner.configure(sweep_config)
    tuner.create()
    # (3) create by constructing progamatic sweep configuration
    tuner = wandb.controller()
    tuner.configure_search('random')
    tuner.configure_program('train-dummy.py')
    tuner.configure_parameter('param1', values=[1,2,3])
    tuner.configure_parameter('param2', values=[1,2,3])
    tuner.configure_controller(type="local")
    tuner.create()

    #
    # run the sweep controller
    #

    # There are three different ways sweeps can be executed:
    # (1) run to completion
    tuner.run()
    # (2) run in a simple loop
    while not tuner.done():
        tuner.step()
        tuner.print_status()
    # (3) run in a more complex loop
    while not tuner.done():
        params = tuner.search()
        tuner.schedule(params)
        runs = tuner.stopping()
        if runs:
            tuner.stop_runs(runs)
"""

from __future__ import print_function

import yaml
import json
import time
import string
import random
import six
from six.moves import urllib
import os

import wandb
from wandb.apis import InternalApi
from wandb import env

# wandb.sweeps.sweeps will be loaded later to prevent dependency requirements for non sweep users.
wandb_sweeps = None

# TODO(jhr): Add metric status
# TODO(jhr): Add print_space
# TODO(jhr): Add print_summary

# This should be something like 'pending' (but we need to make sure everyone else is ok with that)
SWEEP_INITIAL_RUN_STATE = 'running'


def _id_generator(size=10, chars=string.ascii_lowercase + string.digits):
    return ''.join(random.choice(chars) for _ in range(size))


def _get_sweep_url(api, sweep_id):
    """Return sweep url if we can figure it out."""
    if api.api_key:
        if api.settings('entity') is None:
            viewer = api.viewer()
            if viewer.get('entity'):
                api.set_setting('entity', viewer['entity'])
        project = api.settings('project')
        if not project:
            return
        if api.settings('entity'):
            return "{base}/{entity}/{project}/sweeps/{sweepid}".format(
                base=api.app_url,
                entity=urllib.parse.quote(api.settings('entity')),
                project=urllib.parse.quote(project),
                sweepid=urllib.parse.quote(sweep_id)
            )


class _Run(object):
    """Run object containing attributes about a run for sweep searching and stopping."""
    def __init__(self, name, state, history, config, summaryMetrics, stopped, shouldStop):
        self.name = name
        self.state = state
        self.config = config
        self.history = history
        self.summaryMetrics = summaryMetrics
        self.stopped = stopped
        self.shouldStop = shouldStop

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
        shouldStop = run_dict['shouldStop']
        r = cls(name, state, history, config, summaryMetrics, stopped, shouldStop)
        return r


class ControllerError(Exception):
    """Base class for sweep errors"""
    pass


class _WandbController():
    """Sweep controller class.

    Internal datastructures on the sweep object to coordinate local controller with
    cloud controller.

    Data structures:
        controller: {
            schedule: [
                { id: SCHEDULE_ID
                  data: {param1: val1, param2: val2}},
            ]
            earlystop: [RUN_ID, ...]
        scheduler:
            scheduled: [
                { id: SCHEDULE_ID
                  runid: RUN_ID},
            ]

    `controller` is only updated by the client
    `scheduler` is only updated by the cloud backend

    Protocols:
        Scheduling a run:
        - client controller adds a schedule entry on the controller.schedule list
        - cloud backend notices the new entry and creates a run with the parameters
        - cloud backend adds a scheduled entry on the scheduler.scheduled list
        - client controller notices that the run has been scheduled and removes it from
          controller.schedule list

    Current implementation details:
        - Runs are only schedule if there are no other runs scheduled.

    """
    def __init__(self, sweep_id_or_config=None, entity=None, project=None):
        global wandb_sweeps
        try:
            from wandb.sweeps import sweeps as wandb_sweeps
        except ImportError as e:
            raise wandb.Error("Module load error: " + str(e))

        # sweep id configured in constuctor
        self._sweep_id = None

        # configured parameters
        # Configuration to be created
        self._create = {}
        # Custom search
        self._custom_search = None
        # Custom stopping
        self._custom_stopping = None
        # Program function (used for future jupyter support)
        self._program_function = None

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

        # Internal
        # Keep track of whether the sweep has been started
        self._started = False
        # indicate whether there is more to schedule
        self._done_scheduling = False
        # indicate whether the sweep needs to be created
        self._defer_sweep_creation = False
        # count of logged lines since last status
        self._logged = 0
        # last status line printed
        self._laststatus = ''
        # keep track of logged actions for print_actions()
        self._log_actions = []
        # keep track of logged debug for print_debug()
        self._log_debug = []

        # all backend commands use internal api
        environ = os.environ
        if entity:
            env.set_entity(entity, env=environ)
        if project:
            env.set_project(project, env=environ)
        self._api = InternalApi(environ=environ)

        if isinstance(sweep_id_or_config, str):
            self._sweep_id = sweep_id_or_config
        elif isinstance(sweep_id_or_config, dict):
            self.configure(sweep_id_or_config)
            self._sweep_id = self.create()
        elif sweep_id_or_config is None:
            self._defer_sweep_creation = True
            return
        else:
            raise ControllerError("Unhandled sweep controller type")
        sweep_obj = self._sweep_object_read_from_backend()
        if sweep_obj is None:
            raise ControllerError("Can not find sweep")
        self._sweep_obj = sweep_obj

    @property
    def sweep_config(self):
        return self._sweep_config

    @property
    def sweep_id(self):
        return self._sweep_id

    def _log(self):
        self._logged += 1

    def _error(self, s):
        print("ERROR:", s)
        self._log()

    def _warn(self, s):
        print("WARN:", s)
        self._log()

    def _info(self, s):
        print("INFO:", s)
        self._log()

    def _debug(self, s):
        print("DEBUG:", s)
        self._log()

    def _configure_check(self):
        if self._started:
            raise ControllerError("Can not configure after sweep has been started.")

    def configure_search(self, search, **kwargs):
        self._configure_check()
        if isinstance(search, str):
            self._create["method"] = search
        elif issubclass(search, wandb_sweeps.base.Search):
            self._create["method"] = 'custom'
            self._custom_search = search(kwargs)
        else:
            raise ControllerError("Unhandled search type.")
    
    def configure_stopping(self, stopping, **kwargs):
        self._configure_check()
        if isinstance(stopping, str):
            self._create.setdefault('early_terminate', {})
            self._create['early_terminate']['type'] = stopping
            for k, v in kwargs.items():
                self._create['early_terminate'][k] = v
        elif issubclass(stopping, wandb_sweeps.base.EarlyTerminate):
            self._custom_stopping = stopping(kwargs)
            self._create.setdefault('early_terminate', {})
            self._create['early_terminate']['type'] = 'custom'
        else:
            raise ControllerError("Unhandled stopping type.")

    def configure_metric(self, metric, goal=None):
        self._configure_check()
        self._create.setdefault('metric', {})
        self._create['metric']['name'] = metric
        if goal:
            self._create['metric']['goal'] = goal

    def configure_program(self, program):
        self._configure_check()
        if isinstance(program, str):
            self._create['program'] = program
        elif hasattr(program, '__call__'):
            self._create['program'] = '__callable__'
            self._program_function = program
            raise ControllerError("Program functions are not supported yet")
        else:
            raise ControllerError("Unhandled sweep program type")

    def configure_name(self, name):
        self._configure_check()
        self._create['name'] = name

    def configure_description(self, description):
        self._configure_check()
        self._create['description'] = description

    def configure_parameter(self, name, values=None, value=None, distribution=None, min=None, max=None, mu=None, sigma=None, q=None):
        self._configure_check()
        self._create.setdefault('parameters', {}).setdefault(name, {})
        if value is not None or (values is None and min is None and max is None and distribution is None):
            self._create['parameters'][name]['value'] = value
        if values is not None:
            self._create['parameters'][name]['values'] = values
        if min is not None:
            self._create['parameters'][name]['min'] = min
        if max is not None:
            self._create['parameters'][name]['max'] = max
        if mu is not None:
            self._create['parameters'][name]['mu'] = mu
        if sigma is not None:
            self._create['parameters'][name]['sigma'] = sigma
        if q is not None:
            self._create['parameters'][name]['q'] = q

    def configure_controller(self, type):
        """configure controller to local if type == 'local'."""
        self._configure_check()
        self._create.setdefault('controller', {})
        self._create['controller'].setdefault('type', type)

    def configure(self, sweep_dict_or_config):
        self._configure_check()
        if self._create:
            raise ControllerError("Already configured.")
        if isinstance(sweep_dict_or_config, dict):
            self._create = sweep_dict_or_config
        elif isinstance(sweep_dict_or_config, str):
            self._create = yaml.safe_load(sweep_dict_or_config)
        else:
            raise ControllerError("Unhandled sweep controller type")

    def create(self):
        if self._started:
            raise ControllerError("Can not create after sweep has been started.")
        if not self._defer_sweep_creation:
            raise ControllerError("Can not use create on already created sweep.")
        if not self._create:
            raise ControllerError("Must configure sweep before create.")
        # Do validation if local controller
        is_local = self._create.get('controller', {}).get('type') == 'local'
        if is_local:
            msg = self._validate(self._create)
            if msg:
                raise ControllerError("Validate Error: %s" % msg)
        # Create sweep
        sweep_id = self._api.upsert_sweep(self._create)
        print('Create sweep with ID:', sweep_id)
        sweep_url = _get_sweep_url(self._api, sweep_id)
        if sweep_url:
            print('Sweep URL:', sweep_url)
        self._sweep_id = sweep_id
        self._defer_sweep_creation = False
        return sweep_id

    def run(self, verbose=None, print_status=True, print_actions=False, print_debug=False):
        if verbose:
            print_status=True
            print_actions=True
            print_debug=True
        self._start_if_not_started()
        while not self.done():
            if print_status:
                self.print_status()
            self.step()
            if print_actions:
                self.print_actions()
            if print_debug:
                self.print_debug()
            time.sleep(5)

    def _sweep_object_read_from_backend(self):
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
        self._sweep_runs_map = {r.name: r for r in self._sweep_runs}

        self._controller = json.loads(sweep_obj.get('controller') or '{}')
        self._scheduler = json.loads(sweep_obj.get('scheduler') or '{}')
        self._controller_prev_step = self._controller.copy()
        return sweep_obj

    def _sweep_object_sync_to_backend(self):
        if self._controller == self._controller_prev_step:
            return
        sweep_obj_id = self._sweep_obj['id']
        controller = json.dumps(self._controller)
        self._api.upsert_sweep(
            self._sweep_config, controller=controller, obj_id=sweep_obj_id)
        self._controller_prev_step = self._controller.copy()

    def _start_if_not_started(self):
        if self._started:
            return
        if self._defer_sweep_creation:
            raise ControllerError("Must specify or create a sweep before running controller.")
        obj = self._sweep_object_read_from_backend()
        if not obj:
            return
        is_local = self._sweep_config.get('controller', {}).get('type') == 'local'
        if not is_local:
            raise ControllerError("Only sweeps with a local controller are currently supported.")
        self._started = True
        # reset controller state, we might want to parse this and decide
        # what we can continue and add a version key, but for now we can
        # be safe and just reset things on start
        self._controller = {}   
        self._sweep_object_sync_to_backend()

    def _parse_scheduled(self):
        scheduled_list = self._scheduler.get('scheduled') or []
        started_ids = []
        stopped_runs = []
        done_runs = []
        for s in scheduled_list:
            runid = s.get('runid')
            objid = s.get('id')
            r = self._sweep_runs_map.get(runid)
            if not r:
                continue
            if r.stopped:
                stopped_runs.append(runid)
            summary = r.summaryMetrics
            if r.state == SWEEP_INITIAL_RUN_STATE and not summary:
                continue
            started_ids.append(objid)
            if r.state != 'running':
                done_runs.append(runid)
        return started_ids, stopped_runs, done_runs

    def _step(self):
        self._start_if_not_started()
        self._sweep_object_read_from_backend()

        started_ids, stopped_runs, done_runs = self._parse_scheduled()

        # Remove schedule entry from controller dict if already scheduled
        schedule_list = self._controller.get('schedule', [])
        new_schedule_list = [s for s in schedule_list if s.get('id') not in started_ids]
        self._controller['schedule'] = new_schedule_list

        # Remove earlystop entry from controller if already stopped
        earlystop_list = self._controller.get('earlystop', [])
        new_earlystop_list = [r for r in earlystop_list if r not in stopped_runs and r not in done_runs]
        self._controller['earlystop'] = new_earlystop_list

        # Clear out step logs
        self._log_actions = []
        self._log_debug = []

    def step(self):
        self._step()
        params = self.search()
        self.schedule(params)
        runs = self.stopping()
        if runs:
            self.stop_runs(runs)

    def done(self):
        self._start_if_not_started()
        state = self._sweep_obj.get('state')
        if state in ('RUNNING', 'PENDING'):
            return False
        return True

    def _search(self):
        sweep = self._sweep_obj.copy()
        sweep['runs'] = self._sweep_runs
        sweep['config'] = self._sweep_config
        search = self._custom_search or wandb_sweeps.Search.to_class(self._sweep_config)
        next_run = search.next_run(sweep)
        if next_run:
            next_run, info = next_run
            if info:
                #print("DEBUG", info)
                pass
        else:
            self._done_scheduling = True
        return next_run

    def search(self):
        self._start_if_not_started()
        params = self._search()
        return params

    def _validate(self, config):
        """Make sure config is valid."""
        sweep = {}
        sweep['config'] = config
        sweep['runs'] = []
        search = self._custom_search or wandb_sweeps.Search.to_class(config)
        try:
            next_run = search.next_run(sweep)
        except Exception as err:
            return str(err)
        try:
            stopper = self._custom_stopping or wandb_sweeps.EarlyTerminate.to_class(config)
            runs = stopper.stop_runs(config, [])
        except Exception as err:
            return str(err)
        if config.get("program") is None:
            return "Config file is missing 'program' specification" 
        return

    def _stopping(self):
        sweep = self._sweep_obj.copy()
        sweep['runs'] = self._sweep_runs
        sweep['config'] = self._sweep_config
        stopper = self._custom_stopping or wandb_sweeps.EarlyTerminate.to_class(self._sweep_config)
        stop_runs, info = stopper.stop_runs(self._sweep_config, sweep['runs'])
        debug_lines = info.get('lines', [])
        if debug_lines:
            self._log_debug += debug_lines

        return stop_runs

    def stopping(self):
        self._start_if_not_started()
        runs = self._stopping()
        return runs

    def schedule(self, params):
        self._start_if_not_started()

        # only schedule one run at a time (for now)
        if self._controller and self._controller.get("schedule"):
            return

        if params:
            param_list = ['%s=%s' % (k, v.get('value')) for k, v in sorted(six.iteritems(params))]
            self._log_actions.append(('schedule', ','.join(param_list)))

        # schedule one run
        schedule_list = []
        schedule_id = _id_generator()
        schedule_list.append(
            {'id': schedule_id, 'data': {'args': params}})
        self._controller["schedule"] = schedule_list

        self._sweep_object_sync_to_backend()

    def stop_runs(self, runs):
        earlystop_list = self._controller.get('earlystop', []) + runs
        earlystop_list = list(set(runs))
        self._log_actions.append(('stop', ','.join(runs)))
        self._controller['earlystop'] = earlystop_list
        self._sweep_object_sync_to_backend()

    def print_status(self):
        status = _sweep_status(self._sweep_obj, self._sweep_config, self._sweep_runs)
        if self._laststatus != status or self._logged:
            print(status)
        self._laststatus = status
        self._logged = 0

    def print_actions(self):
        for action, line in self._log_actions:
            self._info('%s (%s)' % (action.capitalize(), line))
        self._log_actions = []

    def print_debug(self):
        for line in self._log_debug:
            self._debug(line)
        self._log_debug = []

    def print_space(self):
        self._warn("Method not implemented yet.")

    def print_summary(self):
        self._warn("Method not implemented yet.")


def controller(sweep_id_or_config=None, entity=None, project=None):
    """Public sweep controller constructor.

    Usage:
        import wandb
        tuner = wandb.controller(...)
        print(tuner.sweep_config)
        print(tuner.sweep_id)
        tuner.configure_search(...)
        tuner.configure_stopping(...)

    """
    c = _WandbController(sweep_id_or_config=sweep_id_or_config, entity=entity, project=project)
    return c


def _get_run_counts(runs):
    metrics = {}
    categories = ('running', 'finished', 'crashed', 'failed')
    for r in runs:
        state = r.state
        found = 'unknown'
        for c in categories:
            if state == c:
                found = c
                break
        metrics.setdefault(found, 0)
        metrics[found] += 1
    return metrics


def _get_runs_status(metrics):
    categories = ('finished', 'crashed', 'failed', 'unknown', 'running')
    mlist = []
    for c in categories:
        if not metrics.get(c):
            continue
        mlist.append("%s: %d" % (c.capitalize(), metrics[c]))
    s = ', '.join(mlist)
    return s


def _sweep_status(sweep_obj, sweep_conf, sweep_runs):
    sweep = sweep_obj['name']
    state = sweep_obj['state']
    run_count = len(sweep_runs)
    run_type_counts = _get_run_counts(sweep_runs)
    stopped = len([r for r in sweep_runs if r.stopped])
    stopping = len([r for r in sweep_runs if r.shouldStop])
    stopstr = ""
    if stopped or stopping:
        stopstr = "Stopped: %d" % stopped
        if stopping:
            stopstr += " (Stopping: %d)" % stopping
    runs_status = _get_runs_status(run_type_counts)
    method = sweep_conf.get('method', 'unknown')
    stopping = sweep_conf.get('early_terminate', None)
    sweep_options = []
    sweep_options.append(method)
    if stopping:
        sweep_options.append(stopping.get('type', 'unknown'))
    sweep_options = ','.join(sweep_options)
    sections = []
    sections.append("Sweep: %s (%s)" % (sweep, sweep_options))
    if runs_status:
        sections.append("Runs: %d (%s)" % (run_count, runs_status))
    else:
        sections.append("Runs: %d" % (run_count))
    if stopstr:
        sections.append(stopstr)
    sections = ' | '.join(sections)
    return sections


def sweep(sweep, entity=None, project=None):
    from wandb.sweeps.config import SweepConfig
    import types

    if isinstance(sweep, types.FunctionType):
        sweep = sweep()
    if isinstance(sweep, SweepConfig):
        sweep = dict(sweep)
    """Sweep create for controller api and jupyter (eventually for cli)."""
    in_jupyter = wandb._get_python_type() != "python"
    if in_jupyter:
        os.environ[env.JUPYTER] = "true"
        _api0 = InternalApi()
        if not _api0.api_key:
            wandb._jupyter_login(api=_api0)
    if entity:
        env.set_entity(entity)
    if project:
        env.set_project(project)
    api = InternalApi()
    sweep_id = api.upsert_sweep(sweep)
    print('Create sweep with ID:', sweep_id)
    sweep_url = _get_sweep_url(api, sweep_id)
    if sweep_url:
        print('Sweep URL:', sweep_url)
    return sweep_id
