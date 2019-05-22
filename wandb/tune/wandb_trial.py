from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

#
# mock interface for ray/tune
#

import collections
import time
import logging
import random
from datetime import datetime
import re
import traceback
import os
import sys

from ray.tune.suggest import BasicVariantGenerator
from ray.tune.schedulers import FIFOScheduler, TrialScheduler
from ray.tune.experiment import Experiment
from ray.tune.trial_executor import TrialExecutor
#from ray.tune.trial_runner import TrialRunner
from ray.tune.trial import Trial, Resources, Checkpoint
from ray.tune.util import warn_if_slow
from ray.tune.result import TIME_THIS_ITER_S, RESULT_DUPLICATE
from ray.tune import TuneError

from wandb.controller import SweepController



DEBUG_PRINT_INTERVAL = 5
RESOURCE_REFRESH_PERIOD = 0.5  # Refresh resources every 500 ms

BOTTLENECK_WARN_PERIOD_S = 60

NONTRIVIAL_WAIT_TIME_THRESHOLD_S = 1e-3

MAX_DEBUG_TRIALS = 20


tune_controller = None
def set_controller(controller):
    global tune_controller
    tune_controller = controller

def wandb_should_schedule():
    global tune_controller
    r = tune_controller.should_schedule()
    return r

def wandb_schedule(x, id=None):
    r = tune_controller.schedule(x, id=id)
    return r

def wandb_stop_trial(x):
    r = tune_controller.stop_trial(x)
    return r

def wandb_get_id(trial):
    r = tune_controller.get_id(trial)
    return r

logger = logging.getLogger(__name__)

class _LocalWrapper(object):
    def __init__(self, result):
        self._result = result

    def unwrap(self):
        """Returns the wrapped result."""
        return self._result


def _naturalize(string):
    """Provides a natural representation for string for nice sorting."""
    splits = re.split("([0-9]+)", string)
    return [int(text) if text.isdigit() else text.lower() for text in splits]

class TrialRunner(object):
    def __init__(self,
                 search_alg,
                 scheduler=None,
                 launch_web_server=False,
                 metadata_checkpoint_dir=None,
                 server_port=0,
                 verbose=True,
                 queue_trials=False,
                 reuse_actors=False,
                 trial_executor=None):
        self._search_alg = search_alg
        self._scheduler_alg = scheduler or FIFOScheduler()
        self.trial_executor = (trial_executor or WandbTrialExecutor(
            queue_trials=queue_trials, reuse_actors=reuse_actors))

        #print("JHRRUNNER", trial_executor, queue_trials)
        # For debugging, it may be useful to halt trials after some time has
        # elapsed. TODO(ekl) consider exposing this in the API.
        #self._global_time_limit = float(
        #    os.environ.get("TRIALRUNNER_WALLTIME_LIMIT", float('inf')))
        self._total_time = 0
        self._iteration = 0
        self._verbose = verbose
        self._queue_trials = queue_trials

        self._server = None
        self._server_port = server_port
        if launch_web_server:
            self._server = TuneServer(self, self._server_port)

        self._trials = []
        self._stop_queue = []
        self._metadata_checkpoint_dir = metadata_checkpoint_dir

        self._start_time = time.time()
        self._session_str = datetime.fromtimestamp(
            self._start_time).strftime("%Y-%m-%d_%H-%M-%S")


    def is_finished(self):
        return False

    def checkpoint(self):
        pass

    # unmodified
    def step(self):
        """Runs one step of the trial event loop.

        Callers should typically run this method repeatedly in a loop. They
        may inspect or modify the runner's state in between calls to step().
        """
        #print("STEP")
        if self.is_finished():
            raise TuneError("Called step when all trials finished?")
        with warn_if_slow("on_step_begin"):
            self.trial_executor.on_step_begin()
        next_trial = self._get_next_trial()  # blocking TODO TODO FIXME FIXME XXX: make blocking
        #print("RUNNINGTRIALS", self.trial_executor.get_running_trials())
        #print("JHRNEXTTRIAL", next_trial)
        if next_trial is not None:
            with warn_if_slow("start_trial"):
                self.trial_executor.start_trial(next_trial)
        elif self.trial_executor.get_running_trials():
            self._process_events()  # blocking
        else:
            #print("NORUNNING")
            for trial in self._trials:
                #print("JHRTRIAL", trial, trial.status)
                ##rapid loop, need to figure out how to make this blocking FIXME TODO
                ##print("GOTTRIAL", trial)
                if trial.status == Trial.PENDING:
                    if not self.has_resources(trial.resources):
                        raise TuneError(
                            ("Insufficient cluster resources to launch trial: "
                             "trial requested {} but the cluster has only {}. "
                             "Pass `queue_trials=True` in "
                             "ray.tune.run() or on the command "
                             "line to queue trials until the cluster scales "
                             "up. {}").format(
                                 trial.resources.summary_string(),
                                 self.trial_executor.resource_string(),
                                 trial._get_trainable_cls().resource_help(
                                     trial.config)))
                elif trial.status == Trial.PAUSED:
                    raise TuneError(
                        "There are paused trials, but no more pending "
                        "trials with sufficient resources.")

        try:
            with warn_if_slow("experiment_checkpoint"):
                self.checkpoint()
        except Exception:
            logger.exception("Trial Runner checkpointing failed.")
        self._iteration += 1

        if self._server or True:
            #print("ISSERVER")
            with warn_if_slow("server"):
                self._process_requests()

            if self.is_finished():
                self._server.shutdown()
        with warn_if_slow("on_step_end"):
            self.trial_executor.on_step_end()

    def debug_string(self, max_debug=MAX_DEBUG_TRIALS):
        messages = self._debug_messages()

        states = collections.defaultdict(set)
        limit_per_state = collections.Counter()
        for t in self._trials:
            states[t.status].add(t)

        # Show at most max_debug total, but divide the limit fairly
        while max_debug > 0:
            start_num = max_debug
            for s in states:
                if limit_per_state[s] >= len(states[s]):
                    continue
                max_debug -= 1
                limit_per_state[s] += 1
            if max_debug == start_num:
                break

        num_trials_per_state = {
            state: len(trials)
            for state, trials in states.items()
        }
        total_number_of_trials = sum(num_trials_per_state.values())
        if total_number_of_trials > 0:
            messages.append("Number of trials: {} ({})"
                            "".format(total_number_of_trials,
                                      num_trials_per_state))

        for state, trials in sorted(states.items()):
            limit = limit_per_state[state]
            messages.append("{} trials:".format(state))
            sorted_trials = sorted(
                trials, key=lambda t: _naturalize(t.experiment_tag))
            if len(trials) > limit:
                tail_length = limit // 2
                first = sorted_trials[:tail_length]
                for t in first:
                    messages.append(" - {}:\t{}".format(
                        t, t.progress_string()))
                messages.append(
                    "  ... {} not shown".format(len(trials) - tail_length * 2))
                last = sorted_trials[-tail_length:]
                for t in last:
                    messages.append(" - {}:\t{}".format(
                        t, t.progress_string()))
            else:
                for t in sorted_trials:
                    messages.append(" - {}:\t{}".format(
                        t, t.progress_string()))

        return "\n".join(messages) + "\n"

    def get_trials(self):
        pass

    def get_trial(self, tid):
        trial = [t for t in self._trials if t.trial_id == tid]
        return trial[0] if trial else None

    def get_trials(self):
        """Returns the list of trials managed by this TrialRunner.

        Note that the caller usually should not mutate trial state directly.
        """

        return self._trials

    def add_trial(self, trial):
        """Adds a new trial to this TrialRunner.

        Trials may be added at any time.

        Args:
            trial (Trial): Trial to queue.
        """
        trial.set_verbose(self._verbose)
        self._trials.append(trial)
        self._scheduler_alg.on_trial_add(self, trial)
        self.trial_executor.try_checkpoint_metadata(trial)

    def _debug_messages(self):
        messages = ["== Status =="]
        messages.append(self._scheduler_alg.debug_string())
        messages.append(self.trial_executor.debug_string())
        #messages.append(self._memory_debug_string())
        return messages

    def _get_next_trial(self):
        """Replenishes queue.

        Blocks if all trials queued have finished, but search algorithm is
        still not finished.
        """
        trials_done = all(trial.is_finished() for trial in self._trials)
        wait_for_trial = trials_done and not self._search_alg.is_finished()
        self._update_trial_queue(blocking=wait_for_trial)
        trial = self._scheduler_alg.choose_trial_to_run(self)
        return trial

    def _update_trial_queue(self, blocking=False, timeout=600):
        """Adds next trials to queue if possible.

        Note that the timeout is currently unexposed to the user.

        Args:
            blocking (bool): Blocks until either a trial is available
                or is_finished (timeout or search algorithm finishes).
            timeout (int): Seconds before blocking times out.
        """
        trials = self._search_alg.next_trials()
        #print("BLOCKING", blocking, trials)
        if blocking and not trials:
            start = time.time()
            # Checking `is_finished` instead of _search_alg.is_finished
            # is fine because blocking only occurs if all trials are
            # finished and search_algorithm is not yet finished
            while (not trials and not self.is_finished()
                   and time.time() - start < timeout):
                logger.info("Blocking for next trial...")
                trials = self._search_alg.next_trials()
                time.sleep(1)

        for trial in trials:
            self.add_trial(trial)

    # unmodified
    def has_resources(self, resources):
        """Returns whether this runner has at least the specified resources."""
        #print("JHR has resources")
        #return False
        return self.trial_executor.has_resources(resources)

    # unmodified
    def _process_events(self):
        #print("JHRPROCEVENTS")
        trial = self.trial_executor.get_next_available_trial()  # blocking
        with warn_if_slow("process_trial"):
            self._process_trial(trial)

    def HACK_process_trial(self, trial):
        result = self.trial_executor.fetch_result(trial)

    # unmodified (except where noted)
    def _process_trial(self, trial):
        try:
            result = self.trial_executor.fetch_result(trial)
            #print("JHR fr:", result)

            is_duplicate = RESULT_DUPLICATE in result
            # TrialScheduler and SearchAlgorithm still receive a
            # notification because there may be special handling for
            # the `on_trial_complete` hook.
            if is_duplicate:
                logger.debug("Trial finished without logging 'done'.")
                result = trial.last_result
                result.update(done=True)

            self._total_time += result[TIME_THIS_ITER_S]

            # JHR added False and
            #if False and trial.should_stop(result):
            if trial.should_stop(result):
                # Hook into scheduler
                self._scheduler_alg.on_trial_complete(self, trial, result)
                self._search_alg.on_trial_complete(
                    trial.trial_id, result=result)
                decision = TrialScheduler.STOP
            else:
                with warn_if_slow("scheduler.on_trial_result"):
                    decision = self._scheduler_alg.on_trial_result(
                        self, trial, result)
                    #print("JHRDECISION:", decision)
                with warn_if_slow("search_alg.on_trial_result"):
                    self._search_alg.on_trial_result(trial.trial_id, result)
                if decision == TrialScheduler.STOP:
                    with warn_if_slow("search_alg.on_trial_complete"):
                        self._search_alg.on_trial_complete(
                            trial.trial_id, early_terminated=True)

            if not is_duplicate:
                trial.update_last_result(
                    result, terminate=(decision == TrialScheduler.STOP))

            # Checkpoints to disk. This should be checked even if
            # the scheduler decision is STOP or PAUSE. Note that
            # PAUSE only checkpoints to memory and does not update
            # the global checkpoint state.
            self._checkpoint_trial_if_needed(trial)

            if decision == TrialScheduler.CONTINUE:
                self.trial_executor.continue_training(trial)
            elif decision == TrialScheduler.PAUSE:
                self.trial_executor.pause_trial(trial)
            elif decision == TrialScheduler.STOP:
                self.trial_executor.export_trial_if_needed(trial)
                self.trial_executor.stop_trial(trial)
            else:
                assert False, "Invalid scheduling decision: {}".format(
                    decision)
        except Exception:
            logger.exception("Error processing event.")
            error_msg = traceback.format_exc()
            if trial.status == Trial.RUNNING:
                if trial.should_recover():
                    self._try_recover(trial, error_msg)
                else:
                    self._scheduler_alg.on_trial_error(self, trial)
                    self._search_alg.on_trial_complete(
                        trial.trial_id, error=True)
                    self.trial_executor.stop_trial(
                        trial, error=True, error_msg=error_msg)

    # unmodified
    def _checkpoint_trial_if_needed(self, trial):
        """Checkpoints trial based off trial.last_result."""
        if trial.should_checkpoint():
            # Save trial runtime if possible
            if hasattr(trial, "runner") and trial.runner:
                self.trial_executor.save(trial, storage=Checkpoint.DISK)
            self.trial_executor.try_checkpoint_metadata(trial)

    # unmodified
    def request_stop_trial(self, trial):
        self._stop_queue.append(trial)

    # unmodified
    def _process_requests(self):
        while self._stop_queue:
            t = self._stop_queue.pop()
            self.stop_trial(t)

    def stop_trial(self, trial):
        """Stops trial.

        Trials may be stopped at any time. If trial is in state PENDING
        or PAUSED, calls `on_trial_remove`  for scheduler and
        `on_trial_complete(..., early_terminated=True) for search_alg.
        Otherwise waits for result for the trial and calls
        `on_trial_complete` for scheduler and search_alg if RUNNING.
        """
        error = False
        error_msg = None

        if trial.status in [Trial.ERROR, Trial.TERMINATED]:
            return
        elif trial.status in [Trial.PENDING, Trial.PAUSED]:
            self._scheduler_alg.on_trial_remove(self, trial)
            self._search_alg.on_trial_complete(
                trial.trial_id, early_terminated=True)
        elif trial.status is Trial.RUNNING:
            try:
                result = self.trial_executor.fetch_result(trial)
                trial.update_last_result(result, terminate=True)
                self._scheduler_alg.on_trial_complete(self, trial, result)
                self._search_alg.on_trial_complete(
                    trial.trial_id, result=result)
            except Exception:
                error_msg = traceback.format_exc()
                logger.exception("Error processing event.")
                self._scheduler_alg.on_trial_error(self, trial)
                self._search_alg.on_trial_complete(trial.trial_id, error=True)
                error = True

        self.trial_executor.stop_trial(trial, error=error, error_msg=error_msg)



# move to wandb_trial_executor
class WandbTrialExecutor(TrialExecutor):
    """An implemention of TrialExecutor based on Ray."""

    def __init__(self,
                 queue_trials=False,
                 reuse_actors=False,
                 refresh_period=RESOURCE_REFRESH_PERIOD):
        super(WandbTrialExecutor, self).__init__(queue_trials)
        self._running = {}
        # Since trial resume after paused should not run
        # trial.train.remote(), thus no more new remote object id generated.
        # We use self._paused to store paused trials here.
        self._paused = {}
        self._reuse_actors = reuse_actors
        self._cached_actor = None

        self._avail_resources = Resources(cpu=0, gpu=0)
        self._committed_resources = Resources(cpu=0, gpu=0)
        self._resources_initialized = False
        self._refresh_period = refresh_period
        self._last_resource_refresh = float("-inf")
        self._last_nontrivial_wait = time.time()
        #if ray.is_initialized():
        #    self._update_avail_resources()

    def resource_string(self):
        """Returns a string describing the total resources available."""

        print("JHRRESOURCE")
        if self._resources_initialized:
            res_str = "{} CPUs, {} GPUs".format(self._avail_resources.cpu,
                                                self._avail_resources.gpu)
            if self._avail_resources.custom_resources:
                custom = ", ".join(
                    "{} {}".format(
                        self._avail_resources.get_res_total(name), name)
                    for name in self._avail_resources.custom_resources)
                res_str += " ({})".format(custom)
            return res_str
        else:
            return "? CPUs, ? GPUs"

    def debug_string(self):
        #return "ImplementMe:WandbTrialExecutor.debug_string()"
        return ""

    def x_has_resources(self, resources):
        return True

    def _update_avail_resources(self, num_retries=5):
        for i in range(num_retries):
            try:
                #JHR resources = ray.global_state.cluster_resources()
                resources = {"CPU": 20, "GPU": 20}
            except Exception:
                # TODO(rliaw): Remove this when local mode is fixed.
                # https://github.com/ray-project/ray/issues/4147
                logger.debug("Using resources for local machine.")
                resources = ray.services.check_and_update_resources(
                    None, None, None)
            if not resources:
                logger.warning("Cluster resources not detected. Retrying...")
                time.sleep(0.5)

        if not resources or "CPU" not in resources:
            raise TuneError("Cluster resources cannot be detected. "
                            "You can resume this experiment by passing in "
                            "`resume=True` to `run`.")

        resources = resources.copy()
        num_cpus = resources.pop("CPU")
        num_gpus = resources.pop("GPU")
        custom_resources = resources

        self._avail_resources = Resources(
            int(num_cpus), int(num_gpus), custom_resources=custom_resources)
        self._last_resource_refresh = time.time()
        self._resources_initialized = True

    # JHR modified
    def export_trial_if_needed(self, trial):
        """Exports model of this trial based on trial.export_formats.

        Return:
            A dict that maps ExportFormats to successfully exported models.
        """
        #if trial.export_formats and len(trial.export_formats) > 0:
        #    return ray.get(
        #        trial.runner.export_model.remote(trial.export_formats))
        return {}

    def has_resources(self, resources):
        """Returns whether this runner has at least the specified resources.

        This refreshes the Ray cluster resources if the time since last update
        has exceeded self._refresh_period. This also assumes that the
        cluster is not resizing very frequently.
        """
        # TODO(jhr): check resources?
        r = wandb_should_schedule()
        return r

        if time.time() - self._last_resource_refresh > self._refresh_period:
            self._update_avail_resources()

        currently_available = Resources.subtract(self._avail_resources,
                                                 self._committed_resources)

        have_space = (
            resources.cpu_total() <= currently_available.cpu
            and resources.gpu_total() <= currently_available.gpu and all(
                resources.get_res_total(res) <= currently_available.get(res)
                for res in resources.custom_resources))

        if have_space:
            return True

        can_overcommit = self._queue_trials

        if (resources.cpu_total() > 0 and currently_available.cpu <= 0) or \
           (resources.gpu_total() > 0 and currently_available.gpu <= 0) or \
           any((resources.get_res_total(res_name) > 0
                and currently_available.get(res_name) <= 0)
               for res_name in resources.custom_resources):
            can_overcommit = False  # requested resource is already saturated

        if can_overcommit:
            logger.warning(
                "Allowing trial to start even though the "
                "cluster does not have enough free resources. Trial actors "
                "may appear to hang until enough resources are added to the "
                "cluster (e.g., via autoscaling). You can disable this "
                "behavior by specifying `queue_trials=False` in "
                "ray.tune.run().")
            return True

        return False


    def xstart_trial(self, trial, checkpoint=None):
        print("Start trial", trial)
        self._start_trial(trial, checkpoint)

    # unmodified
    def start_trial(self, trial, checkpoint=None):
        print("Start trial", trial)
        self._commit_resources(trial.resources)
        try:
            self._start_trial(trial, checkpoint)
        except Exception as e:
            logger.exception("Error starting runner for Trial %s", str(trial))
            error_msg = traceback.format_exc()
            time.sleep(2)
            self._stop_trial(trial, error=True, error_msg=error_msg)
            if isinstance(e, AbortTrialExecution):
                return  # don't retry fatal Tune errors
            try:
                # This forces the trial to not start from checkpoint.
                trial.clear_checkpoint()
                logger.info(
                    "Trying to start runner for Trial %s without checkpoint.",
                    str(trial))
                self._start_trial(trial)
            except Exception:
                logger.exception(
                    "Error starting runner for Trial %s, aborting!",
                    str(trial))
                error_msg = traceback.format_exc()
                self._stop_trial(trial, error=True, error_msg=error_msg)
                # note that we don't return the resources, since they may
                # have been lost


    # unmodified
    def _start_trial(self, trial, checkpoint=None):
        """Starts trial and restores last result if trial was paused.

        Raises:
            ValueError if restoring from checkpoint fails.
        """
        prior_status = trial.status
        self.set_status(trial, Trial.RUNNING)
        trial.runner = self._setup_runner(
            trial,
            reuse_allowed=checkpoint is not None
            or trial._checkpoint.value is not None)
        if not self.restore(trial, checkpoint):
            if trial.status == Trial.ERROR:
                raise RuntimeError(
                    "Restore from checkpoint failed for Trial {}.".format(
                        str(trial)))

        previous_run = self._find_item(self._paused, trial)
        if (prior_status == Trial.PAUSED and previous_run):
            # If Trial was in flight when paused, self._paused stores result.
            self._paused.pop(previous_run[0])
            self._running[previous_run[0]] = trial
        else:
            self._train(trial)

    def x_setup_runner(self, trial, reuse_allowed):
        pass

    def _setup_runner(self, trial, reuse_allowed):
        if (self._reuse_actors and reuse_allowed
                and self._cached_actor is not None):
            logger.debug("Reusing cached runner {} for {}".format(
                self._cached_actor, trial.trial_id))
            existing_runner = self._cached_actor
            self._cached_actor = None
        else:
            if self._cached_actor:
                logger.debug(
                    "Cannot reuse cached runner {} for new trial".format(
                        self._cached_actor))
                self._cached_actor.stop.remote()
                self._cached_actor.__ray_terminate__.remote()
                self._cached_actor = None
            existing_runner = None
            #print("JHR ray remote")
            #cls = ray.remote(
            #    num_cpus=trial.resources.cpu,
            #    num_gpus=trial.resources.gpu,
            #    resources=trial.resources.custom_resources)(
            #        trial._get_trainable_cls())

        trial.init_logger()
        # We checkpoint metadata here to try mitigating logdir duplication
        self.try_checkpoint_metadata(trial)
        remote_logdir = trial.logdir

        if existing_runner:
            trial.runner = existing_runner
            if not self.reset_trial(trial, trial.config, trial.experiment_tag):
                raise AbortTrialExecution(
                    "Trial runner reuse requires reset_trial() to be "
                    "implemented and return True.")
            return existing_runner

        def logger_creator(config):
            # Set the working dir in the remote process, for user file writes
            if not os.path.exists(remote_logdir):
                os.makedirs(remote_logdir)
            os.chdir(remote_logdir)
            return NoopLogger(config, remote_logdir)

        # Logging for trials is handled centrally by TrialRunner, so
        # configure the remote runner to use a noop-logger.
        #return cls.remote(config=trial.config, logger_creator=logger_creator)
        #print("JHR ray cls remote")

    def restore(self, trial, checkpoint=None):
        pass

    def _find_item(self, dictionary, item):
        out = [rid for rid, t in dictionary.items() if t is item]
        return out

    def _train(self, trial):
        """Start one iteration of training and save remote id."""

        assert trial.status == Trial.RUNNING, trial.status
        #remote = trial.runner.train.remote()

        # Local Mode
        #if isinstance(remote, dict):
        #    remote = _LocalWrapper(remote)
        remote = getattr(trial, 'wandb_remote', None)
        if not remote:
            remote = _wandb_remote_get(trial)
            trial.wandb_remote = remote

        self._running[remote] = trial
        #print("JHR_train")

    # JHR unmodified
    def continue_training(self, trial):
        """Continues the training of this trial."""

        self._train(trial)

    # JHR unmodified
    def pause_trial(self, trial):
        """Pauses the trial.

        If trial is in-flight, preserves return value in separate queue
        before pausing, which is restored when Trial is resumed.
        """

        trial_future = self._find_item(self._running, trial)
        if trial_future:
            self._paused[trial_future[0]] = trial
        super(WandbTrialExecutor, self).pause_trial(trial)

    def reset_trial(self, trial, new_config, new_experiment_tag):
        """Tries to invoke `Trainable.reset_config()` to reset trial.

        Args:
            trial (Trial): Trial to be reset.
            new_config (dict): New configuration for Trial
                trainable.
            new_experiment_tag (str): New experiment name
                for trial.

        Returns:
            True if `reset_config` is successful else False.
        """
        #TODO(jhr): implement me?
        BLAH
        trial.experiment_tag = new_experiment_tag
        trial.config = new_config
        trainable = trial.runner
        with warn_if_slow("reset_config"):
            reset_val = ray.get(trainable.reset_config.remote(new_config))
        return reset_val

    def get_running_trials(self):
        """Returns the running trials."""
        #print("JHRRUNNING", self._running.values())

        return list(self._running.values())

    def get_next_available_trial(self):
        shuffled_results = list(self._running.keys())
        random.shuffle(shuffled_results)
        # Note: We shuffle the results because `ray.wait` by default returns
        # the first available result, and we want to guarantee that slower
        # trials (i.e. trials that run remotely) also get fairly reported.
        # See https://github.com/ray-project/ray/issues/4211 for details.
        start = time.time()
        #[result_id], _ = ray.wait(shuffled_results)
        [result_id], _ = wandb_ray_wait(shuffled_results)
        wait_time = time.time() - start
        if wait_time > NONTRIVIAL_WAIT_TIME_THRESHOLD_S:
            self._last_nontrivial_wait = time.time()
        if time.time() - self._last_nontrivial_wait > BOTTLENECK_WARN_PERIOD_S:
            logger.warn(
                "Over the last {} seconds, the Tune event loop has been "
                "backlogged processing new results. Consider increasing your "
                "period of result reporting to improve performance.".format(
                    BOTTLENECK_WARN_PERIOD_S))

            self._last_nontrivial_wait = time.time()
        return self._running[result_id]

    def xfetch_result(self, trial):
        """Fetches one result of the running trials.

        Returns:
            Result of the most recent trial training run."""
        trial_future = self._find_item(self._running, trial)
        if not trial_future:
            raise ValueError("Trial was not running.")
        self._running.pop(trial_future[0])
        #result = ray.get(trial_future[0])
        result = "JHRhack"
        print("FAKERESULTJHR")

        # For local mode
        #if isinstance(result, _LocalWrapper):
        #    result = result.unwrap()
        return result

    # unmodified - almost JHR
    def fetch_result(self, trial):
        """Fetches one result of the running trials.

        Returns:
            Result of the most recent trial training run."""
        trial_future = self._find_item(self._running, trial)
        if not trial_future:
            raise ValueError("Trial was not running.")
        self._running.pop(trial_future[0])
        with warn_if_slow("fetch_result"):
            #JHR result = ray.get(trial_future[0])
            result = wandb_ray_get(trial_future[0])

        # For local mode
        if isinstance(result, _LocalWrapper):
            result = result.unwrap()
        return result

    # unmodified - modified JHR
    def stop_trial(self, trial, error=False, error_msg=None, stop_logger=True):
        """Only returns resources if resources allocated."""
        prior_status = trial.status
        self._stop_trial(
            trial, error=error, error_msg=error_msg, stop_logger=stop_logger)
        if prior_status == Trial.RUNNING:
            logger.debug("Returning resources for Trial %s.", str(trial))
            #JHR#self._return_resources(trial.resources)
            self._return_resources(trial.resources)
            out = self._find_item(self._running, trial)
            for result_id in out:
                self._running.pop(result_id)

    # unmodified
    def _stop_trial(self, trial, error=False, error_msg=None,
                    stop_logger=True):
        """Stops this trial.

        Stops this trial, releasing all allocating resources. If stopping the
        trial fails, the run will be marked as terminated in error, but no
        exception will be thrown.

        Args:
            error (bool): Whether to mark this trial as terminated in error.
            error_msg (str): Optional error message.
            stop_logger (bool): Whether to shut down the trial logger.
        """

        if stop_logger:
            trial.close_logger()

        if error:
            self.set_status(trial, Trial.ERROR)
        else:
            self.set_status(trial, Trial.TERMINATED)

        try:
            trial.write_error_log(error_msg)
            wandb_stop_trial(trial)
            if hasattr(trial, 'runner') and trial.runner:
                if (not error and self._reuse_actors
                        and self._cached_actor is None):
                    logger.debug("Reusing actor for {}".format(trial.runner))
                    self._cached_actor = trial.runner
                else:
                    logger.info(
                        "Destroying actor for trial {}. If your trainable is "
                        "slow to initialize, consider setting "
                        "reuse_actors=True to reduce actor creation "
                        "overheads.".format(trial))
                    trial.runner.stop.remote()
                    trial.runner.__ray_terminate__.remote()
        except Exception:
            logger.exception("Error stopping runner for Trial %s", str(trial))
            self.set_status(trial, Trial.ERROR)
        finally:
            trial.runner = None

    # unmodified
    def _commit_resources(self, resources):
        committed = self._committed_resources
        all_keys = set(resources.custom_resources).union(
            set(committed.custom_resources))

        custom_resources = {
            k: committed.get(k) + resources.get_res_total(k)
            for k in all_keys
        }

        self._committed_resources = Resources(
            committed.cpu + resources.cpu_total(),
            committed.gpu + resources.gpu_total(),
            custom_resources=custom_resources)

    # unmodified
    def _return_resources(self, resources):
        committed = self._committed_resources

        all_keys = set(resources.custom_resources).union(
            set(committed.custom_resources))

        custom_resources = {
            k: committed.get(k) - resources.get_res_total(k)
            for k in all_keys
        }
        self._committed_resources = Resources(
            committed.cpu - resources.cpu_total(),
            committed.gpu - resources.gpu_total(),
            custom_resources=custom_resources)

        assert self._committed_resources.is_nonnegative(), (
            "Resource invalid: {}".format(resources))


def _find_checkpoint_dir(exp):
    # TODO(rliaw): Make sure the checkpoint_dir is resolved earlier.
    # Right now it is resolved somewhere far down the trial generation process
    return os.path.join(exp.spec["local_dir"], exp.name)


def _prompt_restore(checkpoint_dir, resume):
    restore = False
    #TODO(jhr): implement me
    return restore


_wandb_objects = {}
def _wandb_remote_get(trial):
    remote = wandb_get_id(trial)
    _wandb_objects[remote] = 1
    wandb_schedule(trial, id=remote)
    return remote


def wandb_ray_wait(object_ids, num_returns=1, timeout=None):
    r, x = tune_controller.wait(object_ids)
    return r, x

def wandb_ray_get(trial):
    result = tune_controller.get(trial)
    return result

def run(run_or_experiment,
        name=None,
        stop=None,
        config=None,
        resources_per_trial=None,
        num_samples=1,
        local_dir=None,
        upload_dir=None,
        trial_name_creator=None,
        loggers=None,
        sync_function=None,
        checkpoint_freq=0,
        checkpoint_at_end=False,
        export_formats=None,
        max_failures=3,
        restore=None,
        search_alg=None,
        scheduler=None,
        with_server=False,
        server_port=0,
        verbose=2,
        resume=False,
        queue_trials=False,
        reuse_actors=False,
        trial_executor=None,
        raise_on_failed_trial=True):

    controller = SweepController(sys.argv[0])
    set_controller(controller)
    controller.create()

    experiment = run_or_experiment
    if not isinstance(run_or_experiment, Experiment):
        experiment = Experiment(
            name, run_or_experiment, stop, config, resources_per_trial,
            num_samples, local_dir, upload_dir, trial_name_creator, loggers,
            sync_function, checkpoint_freq, checkpoint_at_end, export_formats,
            max_failures, restore)
    else:
        logger.debug("Ignoring some parameters passed into tune.run.")

    checkpoint_dir = "."
    checkpoint_dir = _find_checkpoint_dir(experiment)
    should_restore = _prompt_restore(checkpoint_dir, resume)

    #print("JHRRUN", queue_trials)
    runner = None
    if should_restore:
        try:
            runner = TrialRunner.restore(checkpoint_dir, search_alg, scheduler,
                                         trial_executor)
        except Exception:
            logger.exception("Runner restore failed. Restarting experiment.")
    else:
        logger.info("Starting a new experiment.")
    

    if not runner:
        scheduler = scheduler or FIFOScheduler()
        search_alg = search_alg or BasicVariantGenerator()

        search_alg.add_configurations([experiment])

        runner = TrialRunner(
            search_alg,
            scheduler=scheduler,
            metadata_checkpoint_dir=checkpoint_dir,
            launch_web_server=with_server,
            server_port=server_port,
            verbose=bool(verbose > 1),
            queue_trials=queue_trials,
            reuse_actors=reuse_actors,
            trial_executor=trial_executor)

    if verbose:
        print(runner.debug_string(max_debug=99999))

    last_debug = 0
    while not runner.is_finished():
        runner.step()
        if time.time() - last_debug > DEBUG_PRINT_INTERVAL:
            if verbose:
                print(runner.debug_string())
            last_debug = time.time()
