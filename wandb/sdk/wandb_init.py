#
# -*- coding: utf-8 -*-
"""
wandb.init() indicates the beginning of a new run. In an ML training pipeline,
you could add wandb.init() to the beginning of your training script as well as
your evaluation script, and each piece steps would be tracked as a run in W&B.
"""

from __future__ import print_function

import datetime
import logging
import os
import time
import traceback

import shortuuid  # type: ignore
import six
import wandb
from wandb import trigger
from wandb.dummy import Dummy, DummyDict
from wandb.errors.error import UsageError
from wandb.integration import sagemaker
from wandb.integration.magic import magic_install
from wandb.util import sentry_exc

from . import wandb_login, wandb_setup
from .backend.backend import Backend
from .lib import filesystem, ipython, module, reporting
from .wandb_helper import parse_config
from .wandb_run import Run
from .wandb_settings import Settings

if wandb.TYPE_CHECKING:  # type: ignore
    from typing import Optional, Union, List, Sequence, Dict, Any  # noqa: F401

logger = None  # logger configured during wandb.init()


def _set_logger(log_object):
    """Configure module logger."""
    global logger
    logger = log_object


def online_status(*args, **kwargs):
    pass


class _WandbInit(object):
    def __init__(self):
        self.kwargs = None
        self.settings = None
        self.config = None
        self.run = None
        self.backend = None

        self._teardown_hooks = []
        self._wl = None
        self._reporter = None

    def setup(self, kwargs):
        """
        Complete setup for wandb.init(). This includes parsing all arguments,
        applying them with settings and enabling logging.
        """
        self.kwargs = kwargs

        self._wl = wandb_setup._setup()
        # Make sure we have a logger setup (might be an early logger)
        _set_logger(self._wl._get_logger())

        # Start with settings from wandb library singleton
        settings: Settings = self._wl._clone_settings()
        settings_param = kwargs.pop("settings", None)
        if settings_param:
            settings._apply_settings(settings_param)

        self._reporter = reporting.setup_reporter(
            settings=settings.duplicate().freeze()
        )

        sm_config = sagemaker.parse_sm_config()
        if sm_config:
            sm_api_key = sm_config.get("wandb_api_key", None)
            sm_run, sm_env = sagemaker.parse_sm_resources()
            if sm_env:
                if sm_api_key:
                    sm_env["WANDB_API_KEY"] = sm_api_key
                settings._apply_environ(sm_env)
                wandb.setup(settings=settings)
            for k, v in six.iteritems(sm_run):
                kwargs.setdefault(k, v)

        # Remove parameters that are not part of settings
        init_config = kwargs.pop("config", None) or dict()
        config_include_keys = kwargs.pop("config_include_keys", None)
        config_exclude_keys = kwargs.pop("config_exclude_keys", None)

        # Add deprecation message once we can better track it and document alternatives
        # if config_include_keys or config_exclude_keys:
        #     wandb.termwarn(
        #       "config_include_keys and config_exclude_keys are deprecated:"
        #       " use config=wandb.helper.parse_config(config_object, include=('key',))"
        #       " or config=wandb.helper.parse_config(config_object, exclude=('key',))"
        #     )

        init_config = parse_config(
            init_config, include=config_include_keys, exclude=config_exclude_keys
        )

        # merge config with sweep or sm (or config file)
        self.config = sm_config or self._wl._config or dict()
        for k, v in init_config.items():
            self.config.setdefault(k, v)

        monitor_gym = kwargs.pop("monitor_gym", None)
        if monitor_gym and len(wandb.patched["gym"]) == 0:
            wandb.gym.monitor()

        tensorboard = kwargs.pop("tensorboard", None)
        sync_tensorboard = kwargs.pop("sync_tensorboard", None)
        if tensorboard or sync_tensorboard and len(wandb.patched["tensorboard"]) == 0:
            wandb.tensorboard.patch()

        magic = kwargs.get("magic")
        if magic not in (None, False):
            magic_install(kwargs)

        # handle login related parameters as these are applied to global state
        anonymous = kwargs.pop("anonymous", None)
        force = kwargs.pop("force", None)

        # TODO: move above parameters into apply_init_login
        settings._apply_init_login(kwargs)

        if not settings._offline and not settings._noop:
            wandb_login._login(anonymous=anonymous, force=force, _disable_warning=True)

        # apply updated global state after login was handled
        settings._apply_settings(wandb.setup()._settings)

        settings._apply_init(kwargs)

        if not settings._offline and not settings._noop:
            user_settings = self._wl._load_user_settings()
            settings._apply_user(user_settings)

        # TODO(jhr): should this be moved? probably.
        d = dict(_start_time=time.time(), _start_datetime=datetime.datetime.now(),)
        settings.update(d)

        if settings._jupyter:
            self._jupyter_setup(settings)

        self._log_setup(settings)

        self.settings = settings.freeze()

    def teardown(self):
        # TODO: currently this is only called on failed wandb.init attempts
        # normally this happens on the run object
        logger.info("tearing down wandb.init")
        for hook in self._teardown_hooks:
            hook()

    def _enable_logging(self, log_fname, run_id=None):
        """
        Enable logging to the global debug log.  This adds a run_id to the log,
        in case of muliple processes on the same machine.
        Currently there is no way to disable logging after it's enabled.
        """
        handler = logging.FileHandler(log_fname)
        handler.setLevel(logging.INFO)

        class WBFilter(logging.Filter):
            def filter(self, record):
                record.run_id = run_id
                return True

        if run_id:
            formatter = logging.Formatter(
                "%(asctime)s %(levelname)-7s %(threadName)-10s:%(process)d "
                "[%(run_id)s:%(filename)s:%(funcName)s():%(lineno)s] %(message)s"
            )
        else:
            formatter = logging.Formatter(
                "%(asctime)s %(levelname)-7s %(threadName)-10s:%(process)d "
                "[%(filename)s:%(funcName)s():%(lineno)s] %(message)s"
            )

        handler.setFormatter(formatter)
        if run_id:
            handler.addFilter(WBFilter())
        logger.propagate = False
        logger.addHandler(handler)
        # TODO: make me configurable
        logger.setLevel(logging.DEBUG)
        # TODO: we may need to close the handler as well...
        self._teardown_hooks.append(lambda: logger.removeHandler(handler))

    def _safe_symlink(self, base, target, name, delete=False):
        # TODO(jhr): do this with relpaths, but i cant figure it out on no sleep
        if not hasattr(os, "symlink"):
            return

        pid = os.getpid()
        tmp_name = os.path.join(base, "%s.%d" % (name, pid))

        if delete:
            try:
                os.remove(os.path.join(base, name))
            except OSError:
                pass
        target = os.path.relpath(target, base)
        try:
            os.symlink(target, tmp_name)
            os.rename(tmp_name, os.path.join(base, name))
        except OSError:
            pass

    def _pause_backend(self):
        if self.backend is not None:
            logger.info("pausing backend")
            self.backend.interface.publish_pause()

    def _resume_backend(self):
        if self.backend is not None:
            logger.info("resuming backend")
            self.backend.interface.publish_resume()

    def _jupyter_teardown(self):
        """Teardown hooks and display saving, called with wandb.finish"""
        logger.info("cleaning up jupyter logic")
        ipython = self.notebook.shell
        self.notebook.save_history()
        # because of how we bind our methods we manually find them to unregister
        for hook in ipython.events.callbacks["pre_run_cell"]:
            if "_resume_backend" in hook.__name__:
                ipython.events.unregister("pre_run_cell", hook)
        for hook in ipython.events.callbacks["post_run_cell"]:
            if "_pause_backend" in hook.__name__:
                ipython.events.unregister("post_run_cell", hook)
        ipython.display_pub.publish = ipython.display_pub._orig_publish
        del ipython.display_pub._orig_publish

    def _jupyter_setup(self, settings):
        """Add magic, hooks, and session history saving"""
        self.notebook = wandb.jupyter.Notebook(settings)
        ipython = self.notebook.shell
        ipython.register_magics(wandb.jupyter.WandBMagics)

        # Monkey patch ipython publish to capture displayed outputs
        if not hasattr(ipython.display_pub, "_orig_publish"):
            logger.info("configuring jupyter hooks %s", self)
            ipython.display_pub._orig_publish = ipython.display_pub.publish
            # Registering resume and pause hooks

            ipython.events.register("pre_run_cell", self._resume_backend)
            ipython.events.register("post_run_cell", self._pause_backend)
            self._teardown_hooks.append(self._jupyter_teardown)

        def publish(data, metadata=None, **kwargs):
            ipython.display_pub._orig_publish(data, metadata=metadata, **kwargs)
            self.notebook.save_display(
                ipython.execution_count, {"data": data, "metadata": metadata}
            )

        ipython.display_pub.publish = publish

    def _log_setup(self, settings):
        """Set up logging from settings."""

        filesystem._safe_makedirs(os.path.dirname(settings.log_user))
        filesystem._safe_makedirs(os.path.dirname(settings.log_internal))
        filesystem._safe_makedirs(os.path.dirname(settings.sync_file))
        filesystem._safe_makedirs(settings.files_dir)

        if settings.symlink:
            self._safe_symlink(
                os.path.dirname(settings.sync_symlink_latest),
                os.path.dirname(settings.sync_file),
                os.path.basename(settings.sync_symlink_latest),
                delete=True,
            )
            self._safe_symlink(
                os.path.dirname(settings.log_symlink_user),
                settings.log_user,
                os.path.basename(settings.log_symlink_user),
                delete=True,
            )
            self._safe_symlink(
                os.path.dirname(settings.log_symlink_internal),
                settings.log_internal,
                os.path.basename(settings.log_symlink_internal),
                delete=True,
            )

        _set_logger(logging.getLogger("wandb"))
        self._enable_logging(settings.log_user)

        self._wl._early_logger_flush(logger)
        logger.info("Logging user logs to {}".format(settings.log_user))
        logger.info("Logging internal logs to {}".format(settings.log_internal))

    def init(self):  # noqa: C901
        trigger.call("on_init", **self.kwargs)
        s = self.settings
        config = self.config
        if s._noop:
            run = Dummy()
            run.config = wandb.wandb_sdk.wandb_config.Config()
            run.config.update(config)
            run.summary = DummyDict()
            run.log = lambda data, *_, **__: run.summary.update(data)
            run.finish = lambda *_, **__: module.unset_globals()
            run.step = 0
            run.resumed = False
            run.disabled = True
            run.id = shortuuid.uuid()
            run.name = "dummy-" + run.id
            run.dir = "/"
            module.set_global(
                run=run,
                config=run.config,
                log=run.log,
                summary=run.summary,
                save=run.save,
                use_artifact=run.use_artifact,
                log_artifact=run.log_artifact,
                plot_table=run.plot_table,
                alert=run.alert,
            )
            return run
        if s.reinit or (s._jupyter and s.reinit is not False):
            if len(self._wl._global_run_stack) > 0:
                if len(self._wl._global_run_stack) > 1:
                    wandb.termwarn(
                        "If you want to track multiple runs concurrently in wandb you should use multi-processing not threads"  # noqa: E501
                    )

                last_id = self._wl._global_run_stack[-1]._run_id
                if s._jupyter:
                    ipython.display_html(
                        "Finishing last run (ID:{}) before initializing another...".format(
                            last_id
                        )
                    )

                self._wl._global_run_stack[-1].finish()

                if s._jupyter:
                    ipython.display_html(
                        "...Successfully finished last run (ID:{}). Initializing new run:<br/><br/>".format(
                            last_id
                        )
                    )
        elif isinstance(wandb.run, Run):
            logger.info("wandb.init() called when a run is still active")
            return wandb.run

        use_redirect = True
        stdout_master_fd, stderr_master_fd = None, None
        stdout_slave_fd, stderr_slave_fd = None, None

        backend = Backend()
        backend.ensure_launched(
            settings=s,
            stdout_fd=stdout_master_fd,
            stderr_fd=stderr_master_fd,
            use_redirect=use_redirect,
        )
        backend.server_connect()
        # Make sure we are logged in
        # wandb_login._login(_backend=backend, _settings=self.settings)

        # resuming needs access to the server, check server_status()?

        run = Run(config=config, settings=s)
        run._set_console(
            use_redirect=use_redirect,
            stdout_slave_fd=stdout_slave_fd,
            stderr_slave_fd=stderr_slave_fd,
        )
        run._set_library(self._wl)
        run._set_backend(backend)
        run._set_reporter(self._reporter)
        run._set_teardown_hooks(self._teardown_hooks)
        # TODO: pass mode to backend
        # run_synced = None

        backend._hack_set_run(run)
        backend.interface.publish_header()

        if s._offline:
            run_proto = backend.interface._make_run(run)
            backend.interface._publish_run(run_proto)
            run._set_run_obj_offline(run_proto)
        else:
            ret = backend.interface.communicate_check_version(
                current_version=wandb.__version__
            )
            if ret:
                if ret.upgrade_message:
                    run._set_upgraded_version_message(ret.upgrade_message)
                if ret.delete_message:
                    run._set_deleted_version_message(ret.delete_message)
                if ret.yank_message:
                    run._set_yanked_version_message(ret.yank_message)
            run._on_init()
            ret = backend.interface.communicate_run(run, timeout=30)
            error_message = None
            if not ret:
                error_message = "Error communicating with backend"
            if ret and ret.error:
                error_message = ret.error.message
            if error_message:
                # Shutdown the backend and get rid of the logger
                # we don't need to do console cleanup at this point
                backend.cleanup()
                self.teardown()
                raise UsageError(error_message)
            run._set_run_obj(ret.run)

        # initiate run (stats and metadata probing)
        _ = backend.interface.communicate_run_start()

        self._wl._global_run_stack.append(run)
        self.run = run
        self.backend = backend
        module.set_global(
            run=run,
            config=run.config,
            log=run.log,
            summary=run.summary,
            save=run.save,
            use_artifact=run.use_artifact,
            log_artifact=run.log_artifact,
            plot_table=run.plot_table,
            alert=run.alert,
        )
        self._reporter.set_context(run=run)
        run._on_start()

        run._freeze()
        return run


def getcaller():
    # py2 doesnt have stack_info
    # src, line, func, stack = logger.findCaller(stack_info=True)
    src, line, func = logger.findCaller()[:3]
    print("Problem at:", src, line, func)


def init(
    job_type: Optional[str] = None,
    dir=None,
    config: Union[Dict, str, None] = None,
    project: Optional[str] = None,
    entity: Optional[str] = None,
    reinit: bool = None,
    tags: Optional[Sequence] = None,
    group: Optional[str] = None,
    name: Optional[str] = None,
    notes: Optional[str] = None,
    magic: Union[dict, str, bool] = None,
    config_exclude_keys=None,
    config_include_keys=None,
    anonymous: Optional[str] = None,
    mode: Optional[str] = None,
    allow_val_change: Optional[bool] = None,
    resume: Optional[Union[bool, str]] = None,
    force: Optional[bool] = None,
    tensorboard=None,  # alias for sync_tensorboard
    sync_tensorboard=None,
    monitor_gym=None,
    save_code=None,
    id=None,
    settings: Union[Settings, Dict[str, Any], None] = None,
) -> Union[Run, Dummy]:
    """Initialize W&B
    Spawns a new process to start or resume a run locally and communicate with a
    wandb server. Should be called before any calls to wandb.log.

    Arguments:
        job_type (str, optional): The type of job running, defaults to 'train'
        dir (str, optional): An absolute path to a directory where metadata will
            be stored.
        config (dict, argparse, or absl.flags, str, optional):
            Sets the config parameters (typically hyperparameters) to store with the
            run. See also wandb.config.
            If dict, argparse or absl.flags: will load the key value pairs into
                the runs config object.
            If str: will look for a yaml file that includes config parameters and
                load them into the run's config object.
        project (str, optional): W&B Project.
        entity (str, optional): W&B Entity.
        reinit (bool, optional): Allow multiple calls to init in the same process.
        tags (list, optional): A list of tags to apply to the run.
        group (str, optional): A unique string shared by all runs in a given group.
        name (str, optional): A display name for the run which does not have to be
            unique.
        notes (str, optional): A multiline string associated with the run.
        magic (bool, dict, or str, optional): magic configuration as bool, dict,
            json string, yaml filename.
        config_exclude_keys (list, optional): string keys to exclude storing in W&B
            when specifying config.
        config_include_keys (list, optional): string keys to include storing in W&B
            when specifying config.
        anonymous (str, optional): Can be "allow", "must", or "never". Controls
            whether anonymous logging is allowed.  Defaults to never.
        mode (str, optional): Can be "online", "offline" or "disabled". Defaults to
            online.
        allow_val_change (bool, optional): allow config values to be changed after
            setting. Defaults to true in jupyter and false otherwise.
        resume (bool, str, optional): Sets the resuming behavior. Should be one of:
            "allow", "must", "never", "auto" or None. Defaults to None.
            Cases:
            - "auto" (or True): automatically resume the previous run on the same machine.
                if the previous run crashed, otherwise starts a new run.
            - "allow": if id is set with init(id="UNIQUE_ID") or WANDB_RUN_ID="UNIQUE_ID"
                and it is identical to a previous run, wandb will automatically resume the
                run with the id. Otherwise wandb will start a new run.
            - "never": if id is set with init(id="UNIQUE_ID") or WANDB_RUN_ID="UNIQUE_ID"
                and it is identical to a previous run, wandb will crash.
            - "must": if id is set with init(id="UNIQUE_ID") or WANDB_RUN_ID="UNIQUE_ID"
                and it is identical to a previous run, wandb will automatically resume the
                run with the id. Otherwise wandb will crash.
            - None: never resumes - if a run has a duplicate run_id the previous run is
                overwritten.
            See https://docs.wandb.com/library/advanced/resuming for more detail.
        force (bool, optional): If true, will cause script to crash if user can't or isn't
            logged in to a wandb server.  If false, will cause script to run in offline
            modes if user can't or isn't logged in to a wandb server. Defaults to false.
        sync_tensorboard (bool, optional): Synchronize wandb logs from tensorboard or
            tensorboardX and saves the relevant events file. Defaults to false.
        monitor_gym: (bool, optional): automatically logs videos of environment when
            using OpenAI Gym (see https://docs.wandb.com/library/integrations/openai-gym)
            Defaults to false.
        save_code (bool, optional): Save the entrypoint or jupyter session history
            source code.
        id (str, optional): A globally unique (per project) identifier for the run. This
            is primarily used for resuming.

    Examples:
        Basic usage
        ```
        wandb.init()
        ```

        Launch multiple runs from the same script
        ```
        for x in range(10):
            with wandb.init(project="my-projo") as run:
                for y in range(100):
                    run.log({"metric": x+y})
        ```

    Raises:
        Exception: if problem.

    Returns:
        A `Run` object.
    """
    assert not wandb._IS_INTERNAL_PROCESS
    kwargs = dict(locals())
    error_seen = None
    except_exit = None
    try:
        wi = _WandbInit()
        wi.setup(kwargs)
        except_exit = wi.settings._except_exit
        try:
            run = wi.init()
            except_exit = wi.settings._except_exit
        except (KeyboardInterrupt, Exception) as e:
            if not isinstance(e, KeyboardInterrupt):
                sentry_exc(e)
            if not (
                wandb.wandb_agent._is_running() and isinstance(e, KeyboardInterrupt)
            ):
                getcaller()
            assert logger
            if wi.settings.problem == "fatal":
                raise
            if wi.settings.problem == "warn":
                pass
            # TODO(jhr): figure out how to make this RunDummy
            run = None
    except UsageError:
        raise
    except KeyboardInterrupt as e:
        assert logger
        logger.warning("interrupted", exc_info=e)
        raise e
    except Exception as e:
        error_seen = e
        traceback.print_exc()
        assert logger
        logger.error("error", exc_info=e)
        # Need to build delay into this sentry capture because our exit hooks
        # mess with sentry's ability to send out errors before the program ends.
        sentry_exc(e, delay=True)
        # reraise(*sys.exc_info())
        # six.raise_from(Exception("problem"), e)
    finally:
        if error_seen:
            wandb.termerror("Abnormal program exit")
            if except_exit:
                os._exit(-1)
            six.raise_from(Exception("problem"), error_seen)
    return run
