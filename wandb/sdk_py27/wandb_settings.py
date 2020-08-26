"""Settings.

This module configures settings which impact wandb runs.

Order of loading settings: (differs from priority)
    defaults
    environment
    wandb.setup(settings=)
    system_config
    workspace_config
    wandb.init(settings=)
    network_org
    network_entity
    network_project

Priority of settings:  See "source" variable.

"""

import collections
import configparser
import copy
import datetime
import getpass
import json
import logging
import os
import platform
import socket
import sys
import tempfile

import six
import wandb
from wandb.lib.git import GitRepo
from wandb.lib.ipython import _get_python_type
from wandb.lib.runid import generate_id

if wandb.TYPE_CHECKING:  # type: ignore
    from typing import (  # noqa: F401 pylint: disable=unused-import
        Dict,
        List,
        Optional,
        Union,
    )

logger = logging.getLogger("wandb")

source = (
    "org",
    "entity",
    "project",
    "system",
    "workspace",
    "env",
    "setup",
    "settings",
    "args",
)

Field = collections.namedtuple("TypedField", ["type", "choices"])


defaults = dict(
    base_url="https://api.wandb.ai",
    show_warnings=2,
    summary_warnings=5,
    # old mode field (deprecated in favor of WANDB_OFFLINE=true)
    _mode=Field(str, ("dryrun", "run", "offline", "online",)),
    # problem: TODO(jhr): Not implemented yet, needs new name?
    _problem=Field(str, ("fatal", "warn", "silent",)),
    console="auto",
    _console=Field(str, ("auto", "redirect", "off", "file", "iowrap",)),
    git_remote="origin",
    ignore_globs=[],
    # anonymous might be set by a config file: "false" and "true"
    #   or from wandb.init(anonymous=) or environment: "allow", "must", "never"
    _anonymous=Field(str, ("allow", "must", "never", "false", "true",)),
)

# env mapping?
env_prefix = "WANDB_"
env_settings = dict(
    entity=None,
    project=None,
    base_url=None,
    api_key=None,
    sweep_id=None,
    mode=None,
    run_group=None,
    job_type=None,
    problem=None,
    console=None,
    offline=None,
    disabled=None,
    config_paths=None,
    run_id=None,
    notebook_name=None,
    host=None,
    username=None,
    disable_code=None,
    anonymous=None,
    ignore_globs=None,
    resume=None,
    root_dir="WANDB_DIR",
    run_name="WANDB_NAME",
    run_notes="WANDB_NOTES",
    run_tags="WANDB_TAGS",
)

env_convert = dict(run_tags=lambda s: s.split(","), ignore_globs=lambda s: s.split(","))


def _build_inverse_map(prefix, d):
    inv_map = dict()
    for k, v in six.iteritems(d):
        v = v or prefix + k.upper()
        inv_map[v] = k
    return inv_map


def _is_kaggle():
    return (
        os.getenv("KAGGLE_KERNEL_RUN_TYPE") is not None
        or "kaggle_environments" in sys.modules  # noqa: W503
    )


def _get_program():
    program = os.getenv(wandb.env.PROGRAM)
    if program:
        return program

    try:
        import __main__  # type: ignore

        return __main__.__file__
    except (ImportError, AttributeError):
        return None


def _get_program_relpath_from_gitrepo(program):
    repo = GitRepo()
    root = repo.root
    if not root:
        root = os.getcwd()
    full_path_to_program = os.path.join(
        root, os.path.relpath(os.getcwd(), root), program
    )
    if os.path.exists(full_path_to_program):
        relative_path = os.path.relpath(full_path_to_program, start=root)
        if "../" in relative_path:
            logger.warning("could not save program above cwd: %s" % program)
            return None
        return relative_path

    logger.warning("could not find program at %s" % program)
    return None


# the setting exposed to users as `dir=` or `WANDB_DIR` is actually
# the `root_dir`. We add the `__stage_dir__` to it to get the full
# `wandb_dir`
def get_wandb_dir(root_dir):
    # We use the hidden version if it already exists, otherwise non-hidden.
    if os.path.exists(os.path.join(root_dir, ".wandb")):
        __stage_dir__ = ".wandb" + os.sep
    else:
        __stage_dir__ = "wandb" + os.sep

    path = os.path.join(root_dir, __stage_dir__)
    if not os.access(root_dir or ".", os.W_OK):
        wandb.termwarn("Path %s wasn't writable, using system temp directory" % path)
        path = os.path.join(tempfile.gettempdir(), __stage_dir__ or ("wandb" + os.sep))

    return path


class CantTouchThis(type):
    def __setattr__(cls, attr, value):
        raise Exception("NO!")


class Settings(six.with_metaclass(CantTouchThis, object)):
    """Settings Constructor

    Args:
        entity: personal user or team to use for Run.
        project: project name for the Run.

    Raises:
        Exception: if problem.

    """

    def __init__(  # pylint: disable=unused-argument
        self,
        base_url = None,
        api_key = None,
        anonymous=None,
        # how do we annotate that: dryrun==offline?
        mode = "run",
        offline = None,
        entity = None,
        project = None,
        run_group = None,
        job_type = None,
        run_id = None,
        run_name = None,
        run_notes = None,
        resume = None,
        magic = False,
        run_tags=None,
        sweep_id=None,
        # compatibility / error handling
        # compat_version=None,  # set to "0.8" for safer defaults for older users
        # strict=None,  # set to "on" to enforce current best practices (also "warn")
        problem="fatal",
        # dynamic settings
        system_sample_seconds=2,
        system_samples=15,
        heartbeat_seconds=30,
        config_paths=None,
        _config_dict=None,
        # directories and files
        root_dir=None,
        wandb_dir=None,  # computed
        settings_system_spec="~/.config/wandb/settings",
        settings_workspace_spec="{wandb_dir}/settings",
        settings_system=None,  # computed
        settings_workspace=None,  # computed
        sync_dir_spec="{wandb_dir}/{run_mode}-{timespec}-{run_id}",
        sync_file_spec="run-{timespec}-{run_id}.wandb",
        # sync_symlink_sync_spec="{wandb_dir}/sync",
        # sync_symlink_offline_spec="{wandb_dir}/offline",
        sync_symlink_latest_spec="{wandb_dir}/latest-run",
        _sync_dir=None,  # computed
        sync_file=None,  # computed
        log_dir_spec="{wandb_dir}/{run_mode}-{timespec}-{run_id}/logs",
        log_user_spec="debug-{timespec}-{run_id}.log",
        log_internal_spec="debug-internal-{timespec}-{run_id}.log",
        log_symlink_user_spec="{wandb_dir}/debug.log",
        log_symlink_internal_spec="{wandb_dir}/debug-internal.log",
        log_user=None,  # computed
        log_internal=None,  # computed
        resume_fname_spec="{wandb_dir}/wandb-resume.json",
        resume_fname=None,  # computed
        files_dir_spec="{wandb_dir}/{run_mode}-{timespec}-{run_id}/files",
        files_dir=None,  # computed
        symlink=None,  # probed
        # where files are temporary stored when saving
        # files_dir=None,
        # data_base_dir="wandb",
        # data_dir="",
        # data_spec="wandb-{timespec}-{pid}-data.bin",
        # run_base_dir="wandb",
        # run_dir_spec="run-{timespec}-{pid}",
        program=None,
        notebook_name=None,
        disable_code=None,
        ignore_globs=None,
        save_code=None,
        program_relpath=None,
        git_remote=None,
        dev_prod=None,  # in old settings files, TODO: support?
        host=None,
        username=None,
        docker=None,
        _start_time=None,
        _start_datetime=None,
        _cli_only_mode=None,  # avoid running any code specific for runs
        console=None,
        disabled=None,  # alias for mode=dryrun, not supported yet
        reinit=None,
        _save_requirements=True,
        # compute environment
        jupyter=None,
        windows=None,
        show_colors=None,
        show_emoji=None,
        show_console=None,
        show_info=None,
        show_warnings=None,
        show_errors=None,
        summary_errors=None,
        summary_warnings=None,
        # special
        _settings=None,
        _environ=None,
        _files=None,
        _early_logger=None,
        _internal_queue_timeout=2,
        _internal_check_process=8,
        _disable_meta=None,
        _disable_stats=None,
        _jupyter_path=None,
        _jupyter_name=None,
        _jupyter_root=None,
        _executable=None,
        _cuda=None,
        _args=None,
        _os=None,
        _python=None,
        _kaggle=None,
        _except_exit=None,
    ):
        kwargs = locals()
        object.__setattr__(self, "_masked_keys", set(["self", "_frozen"]))
        object.__setattr__(
            self, "_unsaved_keys", set(["_settings", "_files", "_environ"])
        )
        object.__setattr__(self, "_frozen", False)
        object.__setattr__(self, "_locked_by", dict)
        object.__setattr__(self, "_configured_by", dict)
        self._setup(kwargs)

        if _files:
            # TODO(jhr): permit setting of config in system and workspace
            settings_system = self._path_convert(
                self.__dict__.get("settings_system_spec")
            )
            self.update(self._load(settings_system), _setter="system")
            settings_workspace = self._path_convert(
                self.__dict__.get("settings_workspace_spec")
            )
            self.update(self._load(settings_workspace), _setter="workspace")
        if _settings:
            self.update(dict(_settings))
        if _environ:
            _logger = _early_logger or logger
            inv_map = _build_inverse_map(env_prefix, env_settings)
            env_dict = dict()
            for k, v in six.iteritems(_environ):
                if not k.startswith(env_prefix):
                    continue
                setting_key = inv_map.get(k)
                if setting_key:
                    conv = env_convert.get(setting_key, None)
                    if conv:
                        v = conv(v)
                    env_dict[setting_key] = v
                else:
                    _logger.info("Unhandled environment var: {}".format(k))

            _logger.info("setting env: {}".format(env_dict))
            self.update(env_dict, _setter="env")
        # TODO: is this the right place to do this?
        self.update(
            {"resume_fname": self._path_convert(self.__dict__.get("resume_fname_spec"))}
        )

    def _path_convert_part(self, path_part, format_dict):
        """convert slashes, expand ~ and other macros."""

        path_parts = path_part.split(os.sep if os.sep in path_part else "/")
        for i in range(len(path_parts)):
            path_parts[i] = path_parts[i].format(**format_dict)
        return path_parts

    def _path_convert(self, *path):
        """convert slashes, expand ~ and other macros."""

        format_dict = dict()
        if self._start_time:
            format_dict["timespec"] = datetime.datetime.strftime(
                self._start_datetime, "%Y%m%d_%H%M%S"
            )
        if self.run_id:
            format_dict["run_id"] = self.run_id
        format_dict["run_mode"] = "offline-run" if self.offline else "run"
        format_dict["proc"] = os.getpid()
        # TODO(cling): hack to make sure we read from local settings
        #              this is wrong if the run_dir changes later
        format_dict["wandb_dir"] = self.wandb_dir or "wandb"

        path_items = []
        for p in path:
            path_items += self._path_convert_part(p, format_dict)
        path = os.path.join(*path_items)
        path = os.path.expanduser(path)
        return path

    def _clear_early_logger(self):
        # TODO(jhr): this is a hack
        object.__setattr__(self, "_early_logger", None)

    def _setup(self, kwargs):
        for k, v in six.iteritems(kwargs):
            if k not in self._unsaved_keys:
                object.__setattr__(self, k, v)

    def __copy__(self):
        """Copy (note that the copied object will not be frozen)."""
        s = Settings()
        s.update(dict(self))
        return s

    def duplicate(self):
        return copy.copy(self)

    def _check_invalid(self, k, v):
        # Check to see if matches choice
        f = defaults.get("_" + k)
        if f and isinstance(f, Field):
            if v is not None and f.choices and v not in f.choices:
                raise TypeError(
                    "Settings field {} set to {} not in {}".format(
                        k, v, ",".join(f.choices)
                    )
                )

    def update(self, __d=None, _setter=None, **kwargs):
        if self._frozen and (__d or kwargs):
            raise TypeError("Settings object is frozen")
        d = __d or dict()
        for check in d, kwargs:
            for k in six.viewkeys(check):
                if k not in self.__dict__:
                    raise KeyError(k)
                self._check_invalid(k, check[k])
        self.__dict__.update({k: v for k, v in d.items() if v is not None})
        self.__dict__.update({k: v for k, v in kwargs.items() if v is not None})

    def _reinfer_settings_from_env(self):
        """As settings change we might want to run this again."""
        # figure out if we are in offline mode
        # (disabled is how it is stored in settings files)
        if self.disabled:
            self.offline = True
        if self.mode in ("dryrun", "offline"):
            self.offline = True

    def _infer_settings_from_env(self):
        """Modify settings based on environment (for runs and cli)."""

        d = {}
        d["jupyter"] = _get_python_type() != "python"
        d["_kaggle"] = _is_kaggle()
        d["windows"] = platform.system() == "Windows"
        # disable symlinks if on windows (requires admin or developer setup)
        d["symlink"] = True
        if d["windows"]:
            d["symlink"] = False
        self.setdefaults(d)

        # TODO(jhr): this needs to be moved last in setting up settings
        u = {}
        if self.console == "auto":
            console = "redirect"
            if self.jupyter:
                console = "off"
            # if self.windows:
            #     console = "off"
            u["console"] = console

        # For code saving, only allow env var override if value from server is true, or
        # if no preference was specified.
        if (self.save_code is True or self.save_code is None) and os.getenv(
            wandb.env.SAVE_CODE
        ) is not None:
            u["save_code"] = wandb.env.should_save_code()

        if self.jupyter:
            meta = wandb.jupyter.notebook_metadata()
            u["_jupyter_path"] = meta.get("path")
            u["_jupyter_name"] = meta.get("name")
            u["_jupyter_root"] = meta.get("root")

        # host and username are populated by env_settings above if their env
        # vars exist -- but if they don't, we'll fill them in here
        if not self.host:
            u["host"] = socket.gethostname()

        if not self.username:
            try:
                u["username"] = getpass.getuser()
            except KeyError:
                # getuser() could raise KeyError in restricted environments like
                # chroot jails or docker containers.  Return user id in these cases.
                u["username"] = str(os.getuid())

        u["_executable"] = sys.executable

        u["docker"] = wandb.env.get_docker(wandb.util.image_id_from_k8s())

        # TODO: we should use the cuda library to collect this
        if os.path.exists("/usr/local/cuda/version.txt"):
            with open("/usr/local/cuda/version.txt") as f:
                u["_cuda"] = f.read().split(" ")[-1].strip()
        u["_args"] = sys.argv[1:]
        u["_os"] = platform.platform(aliased=True)
        u["_python"] = platform.python_version()
        # hack to make sure we don't hang on windows
        if self.windows and self._except_exit is None:
            u["_except_exit"] = True

        self.update(u)
        self._reinfer_settings_from_env()

    def _infer_run_settings_from_env(self):
        """Modify settings based on environment (for runs only)."""
        # If the settings say to save code, and there's not already a program file,
        # infer it now.
        if self.save_code and not self.program_relpath:
            program = _get_program()
            if program:
                program_relpath = _get_program_relpath_from_gitrepo(program)
                self.update(dict(program=program, program_relpath=program_relpath))
            else:
                program = "<python with no main file>"
                self.update(dict(program=program))

    def setdefaults(self, __d=None):
        __d = __d or defaults
        # set defaults
        for k, v in __d.items():
            if not k.startswith("_"):
                if self.__dict__.get(k) is None:
                    object.__setattr__(self, k, v)

    def save(self, fname):
        pass

    def load(self, fname):
        pass

    def __setattr__(self, name, value):
        if name not in self.__dict__:
            raise AttributeError(name)
        if self._frozen:
            raise TypeError("Settings object is frozen")
        self._check_invalid(name, value)
        object.__setattr__(self, name, value)

    def keys(self):
        return tuple(k for k in self.__dict__ if k not in self._masked_keys)

    def __getitem__(self, k):
        return self.__dict__[k]

    def freeze(self):
        object.__setattr__(self, "_frozen", True)
        return self

    @property
    def frozen(self):
        return self._frozen

    def _load(self, fname):
        section = "default"
        cp = configparser.ConfigParser()
        cp.add_section(section)
        cp.read(fname)
        d = dict()
        for k in cp[section]:
            d[k] = cp[section][k]
            # TODO (cvp): we didn't do this in the old cli, but it seems necessary
            if k == "ignore_globs":
                d[k] = d[k].split(",")
        return d

    def apply_init(self, args):
        # strip out items where value is None
        param_map = dict(
            name="run_name",
            id="run_id",
            tags="run_tags",
            group="run_group",
            dir="root_dir",
        )
        args = {param_map.get(k, k): v for k, v in six.iteritems(args) if v is not None}
        # fun logic to convert the resume init arg
        if args.get("resume") is not None:
            if isinstance(args["resume"], six.string_types):
                if args["resume"] not in ("allow", "must", "never", "auto"):
                    if args.get("run_id") is None:
                        #  TODO: deprecate or don't support
                        args["run_id"] = args["resume"]
                    args["resume"] = "allow"
            elif args["resume"] is True:
                args["resume"] = "auto"
        self.update(args)
        self.wandb_dir = get_wandb_dir(self.root_dir or "")
        # handle auto resume logic
        if self.resume == "auto":
            if os.path.exists(self.resume_fname):
                with open(self.resume_fname) as f:
                    resume_run_id = json.load(f)["run_id"]
                if self.run_id is None:
                    self.run_id = resume_run_id
                else:
                    wandb.termwarn(
                        "Tried to auto resume run with id %s but id %s is set."
                        % (resume_run_id, self.run_id)
                    )
        self.run_id = self.run_id or generate_id()
        # persist our run id incase of failure
        if self.resume == "auto":
            wandb.util.mkdir_exists_ok(self.wandb_dir)
            with open(self.resume_fname, "w") as f:
                f.write(json.dumps({"run_id": self.run_id}))
        self._reinfer_settings_from_env()
