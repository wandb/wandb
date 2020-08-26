# -*- coding: utf-8 -*-
"""Run - Run object.

Manage wandb run.

"""

from __future__ import print_function

import atexit
import collections
import glob
import json
import logging
import numbers
import os
import platform
import sys
import threading
import time
import traceback

import click
from six import iteritems, string_types
from six.moves import _thread as thread
from six.moves.urllib.parse import quote as url_quote
import wandb
from wandb import trigger
from wandb.apis import internal, public
from wandb.data_types import _datatypes_set_callback
from wandb.errors import Error
from wandb.interface.summary_record import SummaryRecord
from wandb.lib import filenames, module, proto_util, redirect, sparkline
from wandb.util import sentry_set_scope, to_forward_slash_path
from wandb.viz import Visualize

from . import wandb_config
from . import wandb_history
from . import wandb_summary

if wandb.TYPE_CHECKING:  # type: ignore
    from typing import Optional

logger = logging.getLogger("wandb")
EXIT_TIMEOUT = 60


class Run(object):
    def __init__(self):
        pass


class RunDummy(Run):
    def __init__(self):
        pass


class ExitHooks(object):
    def __init__(self):
        self.exit_code = 0
        self.exception = None

    def hook(self):
        self._orig_exit = sys.exit
        sys.exit = self.exit
        sys.excepthook = self.exc_handler

    def exit(self, code=0):
        orig_code = code
        if code is None:
            code = 0
        elif not isinstance(code, int):
            code = 1
        self.exit_code = code
        self._orig_exit(orig_code)

    def was_ctrl_c(self):
        return isinstance(self.exception, KeyboardInterrupt)

    def exc_handler(self, exc_type, exc, *tb):
        self.exit_code = 1
        self.exception = exc
        if issubclass(exc_type, Error):
            wandb.termerror(str(exc))

        if self.was_ctrl_c():
            self.exit_code = 255

        traceback.print_exception(exc_type, exc, *tb)


class RunStatusChecker(object):
    """Periodically polls the background process for relevant updates.

    For now, we just use this to figure out if the user has requested a stop.
    """

    def __init__(self, interface, polling_interval=15):
        self._interface = interface
        self._polling_interval = polling_interval

        self._join_event = threading.Event()
        self._thread = threading.Thread(target=self.check_status)
        self._thread.daemon = True
        self._thread.start()

    def check_status(self):
        join_requested = False
        while not join_requested:
            status_response = (
                # 'or False' because this could return None.
                self._interface.communicate_status(check_stop_req=True)
                or False
            )
            if status_response.run_should_stop:
                thread.interrupt_main()
                return
            join_requested = self._join_event.wait(self._polling_interval)

    def stop(self):
        self._join_event.set()

    def join(self):
        self.stop()
        self._thread.join()


class RunManaged(Run):
    def __init__(self, config=None, settings=None):
        self._config = wandb_config.Config()
        self._config._set_callback(self._config_callback)
        self._config._set_settings(settings)
        self._backend = None
        self.summary = wandb_summary.Summary(
            self._summary_get_current_summary_callback,
        )
        self.summary._set_update_callback(self._summary_update_callback)
        self.history = wandb_history.History(self)
        self.history._set_callback(self._history_callback)

        _datatypes_set_callback(self._datatypes_callback)

        self._settings = settings
        self._wl = None
        self._reporter = None
        self._data = dict()

        self._entity = None
        self._project = None
        self._group = None
        self._job_type = None
        self._run_id = settings.run_id
        self._start_time = time.time()
        self._starting_step = 0
        self._name = None
        self._notes = None
        self._tags = None

        self._hooks = None
        self._teardown_hooks = []
        self._redirect_cb = None
        self._out_redir = None
        self._err_redir = None
        self.stdout_redirector = None
        self.stderr_redirector = None
        self._save_stdout = None
        self._save_stderr = None
        self._stdout_slave_fd = None
        self._stderr_slave_fd = None
        self._exit_code = None
        self._exit_result = None
        self._final_summary = None
        self._sampled_history = None

        self._output_writer = None

        # Pull info from settings
        self._init_from_settings(settings)

        # Initial scope setup for sentry. This might get changed when the
        # actual run comes back.
        sentry_set_scope("user", self._entity, self._project)

        # Returned from backend request_run(), set from wandb_init?
        self._run_obj = None

        # Created when the run "starts".
        self._run_status_checker = None

        self._poll_exit_response = None

        config = config or dict()
        wandb_key = "_wandb"
        config.setdefault(wandb_key, dict())

        wandb_data = dict()
        wandb_data["cli_version"] = wandb.__version__
        wandb_data["python_version"] = platform.python_version()
        wandb_data["is_jupyter_run"] = settings.jupyter or False
        wandb_data["is_kaggle_kernel"] = settings._kaggle or False
        hf_version = huggingface_version()
        if hf_version:
            wandb_data["huggingface_version"] = hf_version
        framework = self._telemetry_get_framework()
        if framework:
            wandb_data["framework"] = framework
        config[wandb_key].update(wandb_data)

        if settings.save_code and settings.program_relpath:
            config[wandb_key]["code_path"] = to_forward_slash_path(
                os.path.join("code", settings.program_relpath)
            )
        self._config._update(config)
        self._atexit_cleanup_called = None
        self._use_redirect = True
        self._progress_step = 0

    def _telemetry_get_framework(self):
        """Get telemetry data for internal config structure."""
        # detect framework by checking what is loaded
        loaded = {}
        loaded["lightgbm"] = sys.modules.get("lightgbm")
        loaded["catboost"] = sys.modules.get("catboost")
        loaded["xgboost"] = sys.modules.get("xgboost")
        loaded["fastai"] = sys.modules.get("fastai")
        loaded["torch"] = sys.modules.get("torch")
        loaded["keras"] = sys.modules.get("keras")  # vanilla keras
        loaded["tensorflow"] = sys.modules.get("tensorflow")
        loaded["sklearn"] = sys.modules.get("sklearn")

        priority = (
            "lightgbm",
            "catboost",
            "xgboost",
            "fastai",
            "torch",
            "keras",
            "tensorflow",
            "sklearn",
        )
        framework = next((f for f in priority if loaded.get(f)), None)
        return framework

    def _init_from_settings(self, settings):
        if settings.entity is not None:
            self._entity = settings.entity
        if settings.project is not None:
            self._project = settings.project
        if settings.run_group is not None:
            self._group = settings.run_group
        if settings.job_type is not None:
            self._job_type = settings.job_type
        if settings.run_name is not None:
            self._name = settings.run_name
        if settings.run_notes is not None:
            self._notes = settings.run_notes
        if settings.run_tags is not None:
            self._tags = settings.run_tags

    def _make_proto_run(self, run):
        """Populate protocol buffer RunData for interface/interface."""
        if self._entity is not None:
            run.entity = self._entity
        if self._project is not None:
            run.project = self._project
        if self._group is not None:
            run.run_group = self._group
        if self._job_type is not None:
            run.job_type = self._job_type
        if self._run_id is not None:
            run.run_id = self._run_id
        if self._name is not None:
            run.display_name = self._name
        if self._notes is not None:
            run.notes = self._notes
        if self._tags is not None:
            for tag in self._tags:
                run.tags.append(tag)
        if self._start_time is not None:
            run.start_time.FromSeconds(int(self._start_time))
        # Note: run.config is set in interface/interface:_make_run()

    def __getstate__(self):
        pass

    def __setstate__(self, state):
        pass

    @property
    def dir(self):
        return self._settings.files_dir

    @property
    def config(self):
        return self._config

    @property
    def name(self):
        if not self._run_obj:
            return None
        return self._run_obj.display_name

    @name.setter
    def name(self, name):
        self._name = name
        if self._backend:
            self._backend.interface.publish_run(self)

    @property
    def notes(self):
        if not self._run_obj:
            return None
        return self._run_obj.notes

    @notes.setter
    def notes(self, notes):
        self._notes = notes
        if self._backend:
            self._backend.interface.publish_run(self)

    @property
    def id(self):
        return self._run_id

    @property
    def path(self):
        parts = []
        for e in [self._entity, self._project, self._run_id]:
            if e is not None:
                parts.append(e)
        return "/".join(parts)

    @property
    def start_time(self):
        if not self._run_obj:
            return self._start_time
        else:
            return self._run_obj.start_time.ToSeconds()

    @property
    def starting_step(self):
        if not self._run_obj:
            return self._starting_step
        else:
            return self._run_obj.starting_step

    @property
    def resumed(self):
        return self._starting_step > 0

    @property
    def step(self):
        return self.history._step

    def project_name(self, api=None):
        if not self._run_obj:
            wandb.termwarn("Project name not available in offline run")
            return
        return self._run_obj.project

    @property
    def entity(self):
        return self._entity

    # def _repr_html_(self):
    #     url = "https://app.wandb.test/jeff/uncategorized/runs/{}".format(
    #       self.run_id)
    #     style = "border:none;width:100%;height:400px"
    #     s = "<h1>Run({})</h1><iframe src=\"{}\" style=\"{}\"></iframe>".format(
    #       self.run_id, url, style)
    #     return s

    def _repr_mimebundle_(self, include=None, exclude=None):
        url = self._get_run_url()
        style = "border:none;width:100%;height:400px"
        note = ""
        if include or exclude:
            note = "(DEBUG: include={}, exclude={})".format(include, exclude)
        s = '<h1>Run({})</h1><p>{}</p><iframe src="{}" style="{}"></iframe>'.format(
            self._run_id, note, url, style
        )
        return {"text/html": s}

    def _config_callback(self, key=None, val=None, data=None):
        logger.info("config_cb %s %s %s", key, val, data)
        self._backend.interface.publish_config(data)

    def _summary_update_callback(self, summary_record: SummaryRecord):
        self._backend.interface.publish_summary(summary_record)

    def _summary_get_current_summary_callback(self):
        ret = self._backend.interface.request_summary()
        return proto_util.dict_from_proto_list(ret.item)

    def _datatypes_callback(self, fname):
        files = dict(files=[(fname, "now")])
        self._backend.interface.publish_files(files)

    def _history_callback(self, row=None, step=None):

        # TODO(jhr): move visualize hack somewhere else
        visualize_persist_config = False
        for k in row:
            if isinstance(row[k], Visualize):
                if "viz" not in self._config["_wandb"]:
                    self._config["_wandb"]["viz"] = dict()
                self._config["_wandb"]["viz"][k] = {
                    "id": row[k].viz_id,
                    "historyFieldSettings": {"key": k, "x-axis": "_step"},
                }
                row[k] = row[k].value
                visualize_persist_config = True
        if visualize_persist_config:
            self._config_callback(data=self._config._as_dict())

        self._backend.interface.publish_history(row, step)

    def _console_callback(self, name, data):
        # logger.info("console callback: %s, %s", name, data)
        self._backend.interface.publish_output(name, data)

    def _tensorboard_callback(self, logdir, save=None):
        logger.info("tensorboard callback: %s, %s", logdir, save)
        save = True if save is None else save
        self._backend.interface.publish_tbdata(logdir, save)

    def _set_library(self, library):
        self._wl = library

    def _set_backend(self, backend):
        self._backend = backend

    def _set_reporter(self, reporter):
        self._reporter = reporter

    def _set_teardown_hooks(self, hooks):
        self._teardown_hooks = hooks

    def _set_run_obj(self, run_obj):
        self._run_obj = run_obj
        # TODO: Update run summary when resuming?
        self.history._update_step()
        # TODO: It feels weird to call this twice..
        sentry_set_scope("user", run_obj.entity, run_obj.project, self._get_run_url())

    def _add_singleton(self, type, key, value):
        """Stores a singleton item to wandb config.

        A singleton in this context is a piece of data that is continually
        logged with the same value in each history step, but represented
        as a single item in the config.

        We do this to avoid filling up history with a lot of repeated uneccessary data

        Add singleton can be called many times in one run and it will only be
        updated when the value changes. The last value logged will be the one
        persisted to the server"""
        value_extra = {"type": type, "key": key, "value": value}

        if type not in self.config["_wandb"]:
            self.config["_wandb"][type] = {}

        if type in self.config["_wandb"][type]:
            old_value = self.config["_wandb"][type][key]
        else:
            old_value = None

        if value_extra != old_value:
            self.config["_wandb"][type][key] = value_extra
            self.config.persist()

    def log(self, data, step=None, commit=None, sync=None):
        """Log a dict to the global run's history.

        wandb.log can be used to log everything from scalars to histograms, media
            and matplotlib plots.

        The most basic usage is wandb.log({'train-loss': 0.5, 'accuracy': 0.9}).
            This will save a history row associated with the run with train-loss=0.5
            and accuracy=0.9. The history values can be plotted on app.wandb.ai or
            on a local server. The history values can also be downloaded through
            the wandb API.

        Logging a value will update the summary values for any metrics logged.
            The summary values will appear in the run table at app.wandb.ai or
            a local server. If a summary value is manually set with for example
            wandb.run.summary["accuracy"] = 0.9 wandb.log will no longer automatically
            update the run's accuracy.

        Logging values don't have to be scalars. Logging any wandb object is supported.
            For example wandb.log({"example": wandb.Image("myimage.jpg")}) will log an
            example image which will be displayed nicely in the wandb UI. See
            https://docs.wandb.com/library/reference/data_types for all of the different
            supported types.

        Logging nested metrics is encouraged and is supported in the wandb API, so
            you could log multiple accuracy values with wandb.log({'dataset-1':
            {'acc': 0.9, 'loss': 0.3} ,'dataset-2': {'acc': 0.8, 'loss': 0.2}})
            and the metrics will be organized in the wandb UI.

        W&B keeps track of a global step so logging related metrics together is
            encouraged, so by default each time wandb.log is called a global step
            is incremented. If it's inconvenient to log related metrics together
            calling wandb.log({'train-loss': 0.5, commit=False}) and then
            wandb.log({'accuracy': 0.9}) is equivalent to calling
            wandb.log({'train-loss': 0.5, 'accuracy': 0.9})

        wandb.log is not intended to be called more than a few times per second.
            If you want to log more frequently than that it's better to aggregate
            the data on the client side or you may get degraded performance.

        Args:
            row (dict, optional): A dict of serializable python objects i.e str,
                ints, floats, Tensors, dicts, or wandb.data_types
            commit (boolean, optional): Save the metrics dict to the wandb server
                and increment the step.  If false wandb.log just updates the current
                metrics dict with the row argument and metrics won't be saved until
                wandb.log is called with commit=True.
            step (integer, optional): The global step in processing. This persists
                any non-committed earlier steps but defaults to not committing the
                specified step.
            sync (boolean, True): This argument is deprecated and currently doesn't
                change the behaviour of wandb.log

        Examples:
            Basic usage
            ```
            wandb.log({'accuracy': 0.9, 'epoch': 5})
            ```

            Incremental logging
            ```
            wandb.log({'loss': 0.2}, commit=False)
            # Somewhere else when I'm ready to report this step:
            wandb.log({'accuracy': 0.8})
            ```

            Histogram
            ```
            wandb.log({"gradients": wandb.Histogram(numpy_array_or_sequence)})
            ```

            Image
            ```
            wandb.log({"examples": [wandb.Image(numpy_array_or_pil, caption="Label")]})
            ```

            Video
            ```
            wandb.log({"video": wandb.Video(numpy_array_or_video_path, fps=4,
                format="gif")})
            ```

            Matplotlib Plot
            ```
            wandb.log({"chart": plt})
            ```

            PR Curve
            ```
            wandb.log({'pr': wandb.plots.precision_recall(y_test, y_probas, labels)})
            ```

            3D Object
            ```
            wandb.log({"generated_samples":
            [wandb.Object3D(open("sample.obj")),
                wandb.Object3D(open("sample.gltf")),
                wandb.Object3D(open("sample.glb"))]})
            ```

            For more examples, see https://docs.wandb.com/library/log

        Raises:
            wandb.Error - if called before wandb.init
            ValueError - if invalid data is passed

        """
        # TODO(cling): sync is a noop for now
        if not isinstance(data, collections.Mapping):
            raise ValueError("wandb.log must be passed a dictionary")

        if any(not isinstance(key, string_types) for key in data.keys()):
            raise ValueError("Key values passed to `wandb.log` must be strings.")

        if step is not None:
            if self.history._step > step:
                wandb.termwarn(
                    (
                        "Step must only increase in log calls.  "
                        "Step {} < {}; dropping {}.".format(
                            step, self.history._step, data
                        )
                    )
                )
                return
            elif step > self.history._step:
                self.history._flush()
                self.history._step = step
        elif commit is None:
            commit = True
        if commit:
            self.history._row_add(data)
        else:
            self.history._row_update(data)

    def save(
        self,
        glob_str: Optional[str] = None,
        base_path: Optional[str] = None,
        policy: str = "live",
    ):
        """ Ensure all files matching *glob_str* are synced to wandb with the policy specified.

        Args:
            glob_str (string): a relative or absolute path to a unix glob or regular
                path.  If this isn't specified the method is a noop.
            base_path (string): the base path to run the glob relative to
            policy (string): on of "live", "now", or "end"
                live: upload the file as it changes, overwriting the previous version
                now: upload the file once now
                end: only upload file when the run ends
        """
        if glob_str is None:
            # noop for historical reasons, run.save() may be called in legacy code
            wandb.termwarn(
                (
                    "Calling run.save without any arguments is deprecated."
                    "Changes to attributes are automatically persisted."
                )
            )
            return True
        if policy not in ("live", "end", "now"):
            raise ValueError(
                'Only "live" "end" and "now" policies are currently supported.'
            )
        if isinstance(glob_str, bytes):
            glob_str = glob_str.decode("utf-8")
        if not isinstance(glob_str, string_types):
            raise ValueError("Must call wandb.save(glob_str) with glob_str a str")

        if base_path is None:
            if os.path.isabs(glob_str):
                base_path = os.path.dirname(glob_str)
                wandb.termwarn(
                    (
                        "Saving files without folders. If you want to preserve "
                        "sub directories pass base_path to wandb.save, i.e. "
                        'wandb.save("/mnt/folder/file.h5", base_path="/mnt")'
                    )
                )
            else:
                base_path = "."
        wandb_glob_str = os.path.relpath(glob_str, base_path)
        if ".." + os.sep in wandb_glob_str:
            raise ValueError("globs can't walk above base_path")
        if glob_str.startswith("gs://") or glob_str.startswith("s3://"):
            wandb.termlog(
                "%s is a cloud storage url, can't save file to wandb." % glob_str
            )
            return []
        files = glob.glob(os.path.join(self.dir, wandb_glob_str))
        warn = False
        if len(files) == 0 and "*" in wandb_glob_str:
            warn = True
        for path in glob.glob(glob_str):
            file_name = os.path.relpath(path, base_path)
            abs_path = os.path.abspath(path)
            wandb_path = os.path.join(self.dir, file_name)
            wandb.util.mkdir_exists_ok(os.path.dirname(wandb_path))
            # We overwrite symlinks because namespaces can change in Tensorboard
            if os.path.islink(wandb_path) and abs_path != os.readlink(wandb_path):
                os.remove(wandb_path)
                os.symlink(abs_path, wandb_path)
            elif not os.path.exists(wandb_path):
                os.symlink(abs_path, wandb_path)
            files.append(wandb_path)
        if warn:
            file_str = "%i file" % len(files)
            if len(files) > 1:
                file_str += "s"
            wandb.termwarn(
                (
                    "Symlinked %s into the W&B run directory, "
                    "call wandb.save again to sync new files."
                )
                % file_str
            )
        files_dict = dict(files=[(wandb_glob_str, policy)])
        self._backend.interface.publish_files(files_dict)
        return files

    def restore(
        self,
        name: str,
        run_path: Optional[str] = None,
        replace: bool = False,
        root: Optional[str] = None,
    ):
        """ Downloads the specified file from cloud storage into the current run directory
        if it doesn't exist.

        Args:
            name: the name of the file
            run_path: optional path to a different run to pull files from
            replace: whether to download the file even if it already exists locally
            root: the directory to download the file to.  Defaults to the current
                directory or the run directory if wandb.init was called.

        Returns:
            None if it can't find the file, otherwise a file object open for reading

        Raises:
            wandb.CommError if it can't find the run
        """

        #  TODO: handle restore outside of a run context?
        api = public.Api()
        api_run = api.run(run_path or self.path)
        if root is None:
            root = self.dir  # TODO: runless else '.'
        path = os.path.join(root, name)
        if os.path.exists(path) and replace is False:
            return open(path, "r")
        files = api_run.files([name])
        if len(files) == 0:
            return None
        return files[0].download(root=root, replace=True)

    def join(self, exit_code=None):
        """Marks a run as finished, and finishes uploading all data.  This is
        used when creating multiple runs in the same process.  We automatically
        call this method when your script exits.
        """
        # detach logger, other setup cleanup
        logger.info("joining run %s", self.path)
        for hook in self._teardown_hooks:
            hook()
        self._atexit_cleanup(exit_code=exit_code)
        if len(self._wl._global_run_stack) > 0:
            self._wl._global_run_stack.pop()
        module.unset_globals()

    def _get_project_url(self):
        s = self._settings
        r = self._run_obj
        app_url = s.base_url.replace("//api.", "//app.")
        url = "{}/{}/{}".format(app_url, url_quote(r.entity), url_quote(r.project))
        return url

    def _get_run_url(self):
        s = self._settings
        r = self._run_obj
        app_url = s.base_url.replace("//api.", "//app.")
        url = "{}/{}/{}/runs/{}".format(
            app_url, url_quote(r.entity), url_quote(r.project), url_quote(r.run_id)
        )
        return url

    def _get_sweep_url(self):
        """Generate a url for a sweep.

        Returns:
            string - url if the run is part of a sweep
            None - if the run is not part of the sweep
        """

        r = self._run_obj
        sweep_id = r.sweep_id
        if not sweep_id:
            return

        app_url = self._settings.base_url.replace("//api.", "//app.")

        return "{base}/{entity}/{project}/sweeps/{sweepid}".format(
            base=app_url,
            entity=url_quote(r.entity),
            project=url_quote(r.project),
            sweepid=url_quote(sweep_id),
        )

    def _get_run_name(self):
        r = self._run_obj
        return r.display_name

    def _display_run(self):
        project_url = self._get_project_url()
        run_url = self._get_run_url()
        sweep_url = self._get_sweep_url()
        if self._settings.jupyter:
            from IPython.core.display import display, HTML  # type: ignore

            sweep_line = (
                'Sweep page: <a href="{}" target="_blank">{}</a><br/>\n'.format(
                    sweep_url, sweep_url
                )
                if sweep_url
                else ""
            )
            docs_html = '<a href="https://docs.wandb.com/integrations/jupyter.html" target="_blank">(Documentation)</a>'  # noqa: E501
            display(
                HTML(
                    """
                Logging results to <a href="https://wandb.com" target="_blank">Weights & Biases</a> {}.<br/>
                Project page: <a href="{}" target="_blank">{}</a><br/>
                {}Run page: <a href="{}" target="_blank">{}</a><br/>
            """.format(  # noqa: E501
                        docs_html,
                        project_url,
                        project_url,
                        sweep_line,
                        run_url,
                        run_url,
                    )
                )
            )
        else:
            emojis = dict(star="", broom="", rocket="")
            if platform.system() != "Windows":
                emojis = dict(star="⭐️", broom="🧹", rocket="🚀")

            wandb.termlog(
                "{} View project at {}".format(
                    emojis.get("star", ""),
                    click.style(project_url, underline=True, fg="blue"),
                )
            )
            if sweep_url:
                wandb.termlog(
                    "{} View sweep at {}".format(
                        emojis.get("broom", ""),
                        click.style(sweep_url, underline=True, fg="blue"),
                    )
                )
            wandb.termlog(
                "{} View run at {}".format(
                    emojis.get("rocket", ""),
                    click.style(run_url, underline=True, fg="blue"),
                )
            )
            if not self._settings.offline:
                wandb.termlog("Run `wandb off` to turn off syncing.")

    def _redirect(self, stdout_slave_fd, stderr_slave_fd):
        console = self._settings.console
        logger.info("redirect: %s", console)

        if console == "redirect":
            logger.info("redirect1")
            out_cap = redirect.Capture(
                name="stdout", cb=self._redirect_cb, output_writer=self._output_writer
            )
            out_redir = redirect.Redirect(
                src="stdout", dest=out_cap, unbuffered=True, tee=True
            )
            err_cap = redirect.Capture(
                name="stderr", cb=self._redirect_cb, output_writer=self._output_writer
            )
            err_redir = redirect.Redirect(
                src="stderr", dest=err_cap, unbuffered=True, tee=True
            )
            try:
                out_redir.install()
                err_redir.install()
                self._out_redir = out_redir
                self._err_redir = err_redir
                logger.info("redirect2")
            except (OSError, AttributeError) as e:
                logger.error("failed to redirect", exc_info=e)
            return

        return

        # TODO(jhr): everything below here is not executed as we only support redir mode
        #
        # from wandb.lib import console as lib_console
        # from wandb.old import io_wrap
        #
        # redirect stdout
        # if platform.system() == "Windows":
        #     lib_console.win32_redirect(stdout_slave_fd, stderr_slave_fd)
        # else:
        #     self._save_stdout = sys.stdout
        #     self._save_stderr = sys.stderr
        #     stdout_slave = os.fdopen(stdout_slave_fd, "wb")
        #     stderr_slave = os.fdopen(stderr_slave_fd, "wb")
        #     stdout_redirector = io_wrap.FileRedirector(sys.stdout, stdout_slave)
        #     stderr_redirector = io_wrap.FileRedirector(sys.stderr, stderr_slave)
        #     stdout_redirector.redirect()
        #     stderr_redirector.redirect()
        #     self.stdout_redirector = stdout_redirector
        #     self.stderr_redirector = stderr_redirector
        # logger.info("redirect done")

    def _restore(self):
        logger.info("restore")
        # TODO(jhr): drain and shutdown all threads
        if self._use_redirect:
            if self._out_redir:
                self._out_redir.uninstall()
            if self._err_redir:
                self._err_redir.uninstall()
            return

        if self.stdout_redirector:
            self.stdout_redirector.restore()
        if self.stderr_redirector:
            self.stderr_redirector.restore()
        if self._save_stdout:
            sys.stdout = self._save_stdout
        if self._save_stderr:
            sys.stderr = self._save_stderr
        logger.info("restore done")

    def _atexit_cleanup(self, exit_code=None):
        if self._backend is None:
            logger.warning("process exited without backend configured")
            return False
        if self._atexit_cleanup_called:
            return
        self._atexit_cleanup_called = True

        exit_code = exit_code or self._hooks.exit_code if self._hooks else 0
        logger.info("got exitcode: %d", exit_code)
        if exit_code == 0:
            # Cleanup our resume file on a clean exit
            if os.path.exists(self._settings.resume_fname):
                os.remove(self._settings.resume_fname)

        self._exit_code = exit_code
        try:
            self._on_finish()
        except KeyboardInterrupt:
            wandb.termerror("Control-C detected -- Run data was not synced")
            os._exit(-1)
        except Exception as e:
            self._console_stop()
            self._backend.cleanup()
            logger.error("Problem finishing run", exc_info=e)
            wandb.termerror("Problem finishing run")
            traceback.print_exception(*sys.exc_info())
            os._exit(-1)
        self._on_final()

    def _console_start(self):
        logger.info("atexit reg")
        self._hooks = ExitHooks()
        self._hooks.hook()
        atexit.register(lambda: self._atexit_cleanup())

        if self._use_redirect:
            # setup fake callback
            self._redirect_cb = self._console_callback

        output_log_path = os.path.join(self.dir, filenames.OUTPUT_FNAME)
        self._output_writer = WriteSerializingFile(open(output_log_path, "wb"))
        self._redirect(self._stdout_slave_fd, self._stderr_slave_fd)

    def _console_stop(self):
        self._restore()
        self._output_writer.close()
        self._output_writer = None

    def _on_start(self):
        if self._settings.offline:
            wandb.termlog("Offline run mode, not syncing to the cloud.")
        wandb.termlog("Tracking run with wandb version {}".format(wandb.__version__))
        if self._settings.offline:
            wandb.termlog(
                (
                    "W&B is disabled in this directory.  "
                    "Run `wandb on` to enable cloud syncing."
                )
            )
        wandb.termlog(
            "Run data is saved locally in {}".format(self._settings._sync_dir)
        )
        if self._run_obj:
            if self.resumed:
                run_state_str = "Resuming run"
            else:
                run_state_str = "Syncing run"
            run_name = self._get_run_name()
            wandb.termlog(
                "{} {}".format(run_state_str, click.style(run_name, fg="yellow"))
            )
            self._display_run()
        print("")
        if self._backend and not self._settings.offline:
            self._run_status_checker = RunStatusChecker(self._backend.interface)
        self._console_start()

    def _pusher_print_status(self, progress, prefix=True, done=False):
        spinner_states = ["-", "\\", "|", "/"]
        line = " %.2fMB of %.2fMB uploaded (%.2fMB deduped)\r" % (
            progress.uploaded_bytes / 1048576.0,
            progress.total_bytes / 1048576.0,
            progress.deduped_bytes / 1048576.0,
        )
        line = spinner_states[self._progress_step % 4] + line
        self._progress_step += 1
        wandb.termlog(line, newline=False, prefix=prefix)

        if done:
            dedupe_fraction = (
                progress.deduped_bytes / float(progress.total_bytes)
                if progress.total_bytes > 0
                else 0
            )
            if dedupe_fraction > 0.01:
                wandb.termlog(
                    "W&B sync reduced upload amount by %.1f%%             "
                    % (dedupe_fraction * 100),
                    prefix=prefix,
                )
            # clear progress line.
            wandb.termlog(" " * 79, prefix=prefix)

    def _on_finish_progress(self, progress, done=None):
        self._pusher_print_status(progress, done=done)

    def _wait_for_finish(self):
        ret = None
        while True:
            ret = self._backend.interface.communicate_poll_exit()
            logger.info("got exit ret: %s", ret)

            done = ret.response.poll_exit_response.done
            pusher_stats = ret.response.poll_exit_response.pusher_stats
            if pusher_stats:
                self._on_finish_progress(pusher_stats, done)
            if done:
                break
            time.sleep(2)
        return ret

    def _on_finish(self):
        trigger.call("on_finished")

        if self._run_status_checker:
            self._run_status_checker.stop()

        # make sure all uncommitted history is flushed
        self.history._flush()

        self._console_stop()
        print("")
        pid = self._backend._internal_pid
        wandb.termlog("Waiting for W&B process to finish, PID {}".format(pid))
        if not self._exit_code:
            wandb.termlog("Program ended successfully.")
        else:
            msg = "Program failed with code {}. ".format(self._exit_code)
            if not self._settings.offline:
                msg += " Press ctrl-c to abort syncing."
            wandb.termlog(msg)

        if self._settings.offline:
            self._backend.interface.publish_exit(self._exit_code)
        else:
            # TODO: we need to handle catastrophic failure better
            # some tests were timing out on sending exit for reasons not clear to me
            self._backend.interface.publish_exit(self._exit_code)

            # Wait for data to be synced
            ret = self._wait_for_finish()

            self._poll_exit_response = ret.response.poll_exit_response

            ret = self._backend.interface.communicate_summary()
            self._final_summary = proto_util.dict_from_proto_list(ret.item)

            ret = self._backend.interface.communicate_sampled_history()
            d = {item.key: item.values_float or item.values_int for item in ret.item}
            self._sampled_history = d

        self._backend.cleanup()

        if self._run_status_checker:
            self._run_status_checker.join()

    def _on_final(self):
        # check for warnings and errors, show log file locations
        # if self._run_obj:
        #    self._display_run()
        # print("DEBUG on finish")
        if self._reporter:
            warning_lines = self._reporter.warning_lines
            if warning_lines:
                wandb.termlog("Warnings:")
                for line in warning_lines:
                    wandb.termlog(line)
                if len(warning_lines) < self._reporter.warning_count:
                    wandb.termlog("More warnings")

            error_lines = self._reporter.error_lines
            if error_lines:
                wandb.termlog("Errors:")
                for line in error_lines:
                    wandb.termlog(line)
                if len(error_lines) < self._reporter.error_count:
                    wandb.termlog("More errors")
        if self._settings.log_user:
            wandb.termlog(
                "Find user logs for this run at: {}".format(self._settings.log_user)
            )
        if self._settings.log_internal:
            wandb.termlog(
                "Find internal logs for this run at: {}".format(
                    self._settings.log_internal
                )
            )
        if self._settings.offline:
            wandb.termlog("You can sync this run to the cloud by running:")
            wandb.termlog(
                click.style(
                    "wandb sync {}".format(self._settings.sync_file), fg="yellow"
                )
            )

        self._show_summary()
        self._show_history()
        self._show_files()

        if self._run_obj:
            run_url = self._get_run_url()
            run_name = self._get_run_name()
            wandb.termlog(
                "\nSynced {}: {}".format(
                    click.style(run_name, fg="yellow"), click.style(run_url, fg="blue")
                )
            )

    def _show_summary(self):
        if self._final_summary:
            logger.info("rendering summary")
            wandb.termlog("Run summary:")
            max_len = max([len(k) for k in self._final_summary.keys()])
            format_str = "  {:>%s} {}" % max_len
            for k, v in iteritems(self._final_summary):
                # arrays etc. might be too large. for now we just don't print them
                if isinstance(v, string_types):
                    if len(v) >= 20:
                        v = v[:20] + "..."
                    wandb.termlog(format_str.format(k, v))
                elif isinstance(v, numbers.Number):
                    wandb.termlog(format_str.format(k, v))

    def _show_history(self):
        if not self._sampled_history:
            return

        # Only print sparklines if the terminal is utf-8
        # In some python 2.7 tests sys.stdout is a 'cStringIO.StringO' object
        #   which doesn't have the attribute 'encoding'
        if not hasattr(sys.stdout, "encoding") or sys.stdout.encoding not in (
            "UTF_8",
            "UTF-8",
        ):
            return

        logger.info("rendering history")
        wandb.termlog("Run history:")
        max_len = max([len(k) for k in self._sampled_history])
        for key in self._sampled_history:
            vals = wandb.util.downsample(self._sampled_history[key], 40)
            if any((not isinstance(v, numbers.Number) for v in vals)):
                continue
            line = sparkline.sparkify(vals)
            format_str = u"  {:>%s} {}" % max_len
            wandb.termlog(format_str.format(key, line))

    def _show_files(self):
        if not self._poll_exit_response or not self._poll_exit_response.file_counts:
            return
        logger.info("logging synced files")
        wandb.termlog(
            "Synced {} W&B file(s), {} media file(s), {} artifact file(s) and {} other file(s)".format(  # noqa:E501
                self._poll_exit_response.file_counts.wandb_count,
                self._poll_exit_response.file_counts.media_count,
                self._poll_exit_response.file_counts.artifact_count,
                self._poll_exit_response.file_counts.other_count,
            )
        )

    def _save_job_spec(self):
        envdict = dict(python="python3.6", requirements=[],)
        varsdict = {"WANDB_DISABLE_CODE": "True"}
        source = dict(
            git="git@github.com:wandb/examples.git", branch="master", commit="bbd8d23",
        )
        execdict = dict(
            program="train.py",
            directory="keras-cnn-fashion",
            envvars=varsdict,
            args=[],
        )
        configdict = (dict(self._config),)
        artifactsdict = dict(dataset="v1",)
        inputdict = dict(config=configdict, artifacts=artifactsdict,)
        job_spec = {
            "kind": "WandbJob",
            "version": "v0",
            "environment": envdict,
            "source": source,
            "exec": execdict,
            "input": inputdict,
        }

        s = json.dumps(job_spec, indent=4)
        spec_filename = filenames.JOBSPEC_FNAME
        with open(spec_filename, "w") as f:
            print(s, file=f)
        self.save(spec_filename)

    # NB: there is a copy of this in wandb_watch.py with the same signature
    def watch(self, models, criterion=None, log="gradients", log_freq=100, idx=None):
        logger.info("Watching")
        # wandb.run.watch(watch)

    def use_artifact(self, artifact_or_name, type=None, aliases=None):
        """ Declare an artifact as an input to a run, call `download` or `file` on \
        the returned object to get the contents locally.

        Args:
            artifact_or_name (str or Artifact): An artifact name.
            May be prefixed with entity/project. Valid names
                can be in the following forms:
                    name:version
                    name:alias
                    digest
                You can also pass an Artifact object created by calling `wandb.Artifact`
            type (str, optional): The type of artifact to use.
            aliases (list, optional): Aliases to apply to this artifact
        Returns:
            A :obj:`Artifact` object.
        """
        r = self._run_obj
        api = internal.Api(default_settings={"entity": r.entity, "project": r.project})
        api.set_current_run_id(self.id)

        if isinstance(artifact_or_name, str):
            name = artifact_or_name
            public_api = public.Api(
                {"entity": r.entity, "project": r.project, "run": self.id}
            )
            artifact = public_api.artifact(type=type, name=name)
            if type is not None and type != artifact.type:
                raise ValueError(
                    "Supplied type {} does not match type {} of artifact {}".format(
                        type, artifact.type, artifact.name
                    )
                )
            api.use_artifact(artifact.id)
            return artifact
        else:
            artifact = artifact_or_name
            if aliases is None:
                aliases = []
            elif isinstance(aliases, str):
                aliases = [aliases]
            if isinstance(artifact_or_name, wandb.Artifact):
                artifact.finalize()
                self._backend.interface.publish_artifact(
                    self, artifact, aliases, is_user_created=True, use_after_commit=True
                )
                return artifact
            elif isinstance(artifact, public.Artifact):
                api.use_artifact(artifact.id)
                return artifact
            else:
                raise ValueError(
                    'You must pass an artifact name (e.g. "pedestrian-dataset:v1"), an instance of wandb.Artifact, or wandb.Api().artifact() to use_artifact'  # noqa: E501
                )

    def log_artifact(self, artifact_or_path, name=None, type=None, aliases=None):
        """ Declare an artifact as output of a run.

        Args:
            artifact_or_path (str or Artifact): A path to the contents of this artifact,
                can be in the following forms:
                    /local/directory
                    /local/directory/file.txt
                    s3://bucket/path
                You can also pass an Artifact object created by calling
                `wandb.Artifact`.
            name (str, optional): An artifact name. May be prefixed with entity/project.
                Valid names can be in the following forms:
                    name:version
                    name:alias
                    digest
                This will default to the basename of the path prepended with the current
                run id  if not specified.
            type (str): The type of artifact to log, examples include "dataset", "model"
            aliases (list, optional): Aliases to apply to this artifact,
                defaults to ["latest"]
        Returns:
            A :obj:`Artifact` object.
        """
        aliases = aliases or ["latest"]
        if isinstance(artifact_or_path, str):
            if name is None:
                name = "run-%s-%s" % (self.id, os.path.basename(artifact_or_path))
            artifact = wandb.Artifact(name, type)
            if os.path.isfile(artifact_or_path):
                artifact.add_file(artifact_or_path)
            elif os.path.isdir(artifact_or_path):
                artifact.add_dir(artifact_or_path)
            elif "://" in artifact_or_path:
                artifact.add_reference(artifact_or_path)
            else:
                raise ValueError(
                    "path must be a file, directory or external"
                    "reference like s3://bucket/path"
                )
        else:
            artifact = artifact_or_path
        if not isinstance(artifact, wandb.Artifact):
            raise ValueError(
                "You must pass an instance of wandb.Artifact or a "
                "valid file path to log_artifact"
            )
        if isinstance(aliases, str):
            aliases = [aliases]
        artifact.finalize()
        self._backend.interface.publish_artifact(self, artifact, aliases)
        return artifact

    def _set_console(self, use_redirect, stdout_slave_fd, stderr_slave_fd):
        self._use_redirect = use_redirect
        self._stdout_slave_fd = stdout_slave_fd
        self._stderr_slave_fd = stderr_slave_fd

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        exit_code = 0 if exc_type is None else 1
        self.join(exit_code)
        return exc_type is None


def huggingface_version():
    if "transformers" in sys.modules:
        trans = wandb.util.get_module("transformers")
        if hasattr(trans, "__version__"):
            return trans.__version__
    return None


class WriteSerializingFile(object):
    """Wrapper for a file object that serializes writes.
    """

    def __init__(self, f):
        self.lock = threading.Lock()
        self.f = f

    def write(self, *args, **kargs):
        self.lock.acquire()
        try:
            self.f.write(*args, **kargs)
            self.f.flush()
        finally:
            self.lock.release()

    def close(self):
        self.f.close()
