# -*- coding: utf-8 -*-
"""Run - Run object.

Manage wandb run.

"""

from __future__ import print_function

import collections
import glob
import json
import logging
import os
import platform

import click
from six import string_types
import wandb
from wandb.apis import internal, public
from wandb.data_types import _datatypes_set_callback
from wandb.util import sentry_set_scope, to_forward_slash_path
from wandb.viz import Visualize

from . import wandb_config
from . import wandb_history
from . import wandb_summary

if wandb.TYPE_CHECKING:  # type: ignore
    from typing import Optional


logger = logging.getLogger("wandb")


class Run(object):
    def __init__(self):
        pass


class RunDummy(Run):
    def __init__(self):
        pass


class RunManaged(Run):
    def __init__(self, config=None, settings=None):
        self._config = wandb_config.Config()
        self._config._set_callback(self._config_callback)
        self.summary = wandb_summary.Summary()
        self.summary._set_callback(self._summary_callback)
        self.history = wandb_history.History()
        self.history._set_callback(self._history_callback)

        _datatypes_set_callback(self._datatypes_callback)

        self._settings = settings
        self._backend = None
        self._reporter = None
        self._data = dict()

        self._entity = None
        self._project = None
        self._group = None
        self._job_type = None
        self._run_id = settings.run_id
        self._name = None
        self._notes = None
        self._tags = None

        # Pull info from settings
        self._init_from_settings(settings)

        # Initial scope setup for sentry. This might get changed when the
        # actual run comes back.
        sentry_set_scope("user", self._entity, self._project)

        # Returned from backend send_run_sync, set from wandb_init?
        self._run_obj = None

        config = config or dict()
        wandb_key = "_wandb"
        config.setdefault(wandb_key, dict())
        config[wandb_key]["cli_version"] = wandb.__version__
        if settings.save_code and settings.code_program:
            config[wandb_key]["code_path"] = to_forward_slash_path(
                os.path.join("code", settings.code_program)
            )
        self._config._update(config)

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

    def project_name(self, api=None):
        # TODO(jhr): this is probably not right needed by dataframes?
        # api = api or self.api
        # return (api.settings('project') or self.auto_project_name(api) or
        #         "uncategorized")
        return self._project

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
        self._backend.interface.send_config(data)

    def _summary_callback(self, key=None, val=None, data=None):
        self._backend.interface.send_summary(data)

    def _datatypes_callback(self, fname):
        files = dict(files=[(fname, "now")])
        self._backend.interface.send_files(files)

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

        self._backend.interface.send_history(row, step)
        self.summary.update(row)

    def _set_backend(self, backend):
        self._backend = backend

    def _set_reporter(self, reporter):
        self._reporter = reporter

    def _set_run_obj(self, run_obj):
        self._run_obj = run_obj
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
        #  TODO: ensure history is pushed on exit for non-added rows
        if commit:
            self.history._row_add(data)
        else:
            self.history._row_update(data)

    def save(
        self, glob_str, base_path = None, policy = "live"
    ):
        """ Ensure all files matching *glob_str* are synced to wandb with the policy specified.

        Args:
            base_path (string): the base path to run the glob relative to
            policy (string): on of "live", "now", or "end"
                live: upload the file as it changes, overwriting the previous version
                now: upload the file once now
                end: only upload file when the run ends
        """
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
        self._backend.interface.send_files(files_dict)
        return files

    def restore(
        self,
        name,
        run_path = None,
        replace = False,
        root = None,
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

    def join(self):
        """Marks a run as finished, and finishes uploading all data.  This is
        used when creating multiple runs in the same process.  We automatically
        call this method when your script exits.
        """
        self._backend.cleanup()

    def _get_project_url(self):
        s = self._settings
        r = self._run_obj
        app_url = s.base_url.replace("//api.", "//app.")
        url = "{}/{}/{}".format(app_url, r.entity, r.project)
        return url

    def _get_run_url(self):
        s = self._settings
        r = self._run_obj
        app_url = s.base_url.replace("//api.", "//app.")
        url = "{}/{}/{}/runs/{}".format(app_url, r.entity, r.project, r.run_id)
        return url

    def _get_run_name(self):
        r = self._run_obj
        return r.display_name

    def _display_run(self):
        emojis = dict(star="", broom="", rocket="")
        if platform.system() != "Windows":
            emojis = dict(star="⭐️", broom="🧹", rocket="🚀")
        project_url = self._get_project_url()
        run_url = self._get_run_url()
        wandb.termlog(
            "{} View project at {}".format(
                emojis.get("star", ""),
                click.style(project_url, underline=True, fg="blue"),
            )
        )
        wandb.termlog(
            "{} View run at {}".format(
                emojis.get("rocket", ""),
                click.style(run_url, underline=True, fg="blue"),
            )
        )

    def on_start(self):
        wandb.termlog("Tracking run with wandb version {}".format(wandb.__version__))
        if self._run_obj:
            run_state_str = "Syncing run"
            run_name = self._get_run_name()
            wandb.termlog(
                "{} {}".format(run_state_str, click.style(run_name, fg="yellow"))
            )
            self._display_run()
        print("")

    def on_finish(self):
        # check for warnings and errors, show log file locations
        # if self._run_obj:
        #    self._display_run()
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
        if self._run_obj:
            run_url = self._get_run_url()
            run_name = self._get_run_name()
            wandb.termlog(
                "Synced {}: {}".format(
                    click.style(run_name, fg="yellow"), click.style(run_url, fg="blue")
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
        spec_filename = "wandb-jobspec.json"
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
            if type is None:
                raise ValueError("type required")
            public_api = public.Api()
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
            if type is not None:
                raise ValueError("cannot specify type when passing Artifact object")
            if isinstance(aliases, str):
                aliases = [aliases]
            if isinstance(artifact_or_name, wandb.Artifact):
                artifact.finalize()
                self._backend.interface.send_artifact(
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
        self._backend.interface.send_artifact(self, artifact, aliases)
        return artifact
