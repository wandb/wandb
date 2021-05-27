import logging
import os
import platform
import posixpath
import signal
import subprocess
import sys

from wandb.errors import ExecutionException

from .abstract import AbstractRunner, AbstractRun
from ..utils import (
    get_conda_command,
    get_entry_point_command,
    get_or_create_conda_env,
    get_run_env_vars,
    generate_docker_image,
    PROJECT_DOCKER_ARGS,
    PROJECT_STORAGE_DIR,
    PROJECT_SYNCHRONOUS,
    PROJECT_USE_CONDA,
    PROJECT_BUILD_DOCKER,
    WANDB_DOCKER_WORKDIR_PATH,
)

_logger = logging.getLogger(__name__)


class LocalSubmittedRun(AbstractRun):
    """
    Instance of ``AbstractRun`` corresponding to a subprocess launched to run an entry point
    command locally.
    """

    def __init__(self, run_id, command_proc):
        super().__init__(run_id)
        self.command_proc = command_proc

    @property
    def id(self):
        return self.command_proc.pid

    def wait(self):
        return self.command_proc.wait() == 0

    def cancel(self):
        # Interrupt child process if it hasn't already exited
        if self.command_proc.poll() is None:
            # Kill the the process tree rooted at the child if it's the leader of its own process
            # group, otherwise just kill the child
            try:
                if self.command_proc.pid == os.getpgid(self.command_proc.pid):
                    os.killpg(self.command_proc.pid, signal.SIGTERM)
                else:
                    self.command_proc.terminate()
            except OSError:
                # The child process may have exited before we attempted to terminate it, so we
                # ignore OSErrors raised during child process termination
                _logger.info(
                    "Failed to terminate child process (PID %s) corresponding to W&B "
                    "run with ID %s. The process may have already exited.",
                    self.command_proc.pid,
                    self._run_id,
                )
            self.command_proc.wait()

    def get_status(self):
        exit_code = self.command_proc.poll()
        if exit_code is None:
            return "running"
        if exit_code == 0:
            return "finished"
        return "failed"


class LocalRunner(AbstractRunner):
    def run(
        self, project_uri, entry_point, params, version, backend_config, experiment_id=None
    ):
        run_id = os.getenv("WANDB_RUN_ID")  # TODO: bad
        build_docker = backend_config[PROJECT_BUILD_DOCKER]
        project = self.fetch_and_validate_project(
            project_uri, version, entry_point, params
        )
        use_conda = backend_config[PROJECT_USE_CONDA]
        synchronous = backend_config[PROJECT_SYNCHRONOUS]
        docker_args = backend_config[PROJECT_DOCKER_ARGS]
        storage_dir = backend_config[PROJECT_STORAGE_DIR]

        # TODO this should be somewhere else, not at the LocalRunner level
        if build_docker:
            project.name = 'test'        # todo this is just hardcoded rn
            entry_cmd = project.get_entry_point(entry_point).command
            image_id = generate_docker_image(project, entry_cmd, self._api)
            project.docker_env = {'image': image_id}

        command_args = []
        command_separator = " "
        # If a docker_env attribute is defined in MLproject then it takes precedence over conda yaml
        # environments, so the project will be executed inside a docker container.
        if project.docker_env:
            from ..docker import (
                validate_docker_env,
                validate_docker_installation,
                build_docker_image,
            )

            validate_docker_env(project)
            validate_docker_installation()
            image = build_docker_image(
                work_dir=project.dir,
                repository_uri=project.name, # todo ??? not sure why this is passed here we should figure out this interface lol
                base_image=project.docker_env.get("image"),
                run_id=run_id,
                api=self._api,
            )
            command_args += _get_docker_command(
                image=image,
                run_id=run_id,
                docker_args=docker_args,
                volumes=project.docker_env.get("volumes"),
                user_env_vars=project.docker_env.get("environment"),
            )

        # Synchronously create a conda environment (even though this may take some time)
        # to avoid failures due to multiple concurrent attempts to create the same conda env.
        elif use_conda:
            command_separator = " && "
            conda_env_name = get_or_create_conda_env(project.conda_env_path)
            command_args += get_conda_command(conda_env_name)
        # In synchronous mode, run the entry point command in a blocking fashion, sending status
        # updates to the tracking server when finished. Note that the run state may not be
        # persisted to the tracking server if interrupted
        if synchronous:
            command_args += get_entry_point_command(
                project, entry_point, params, storage_dir
            )
            command_str = command_separator.join(command_args)

            command_str += " " + " ".join(project.args)
            print("Launching run in docker with command: {}".format(command_str))
            return _run_entry_point(
                command_str, project.dir, experiment_id, run_id=run_id
            )
        # Otherwise, invoke `wandb launch` in a subprocess
        return _invoke_wandb_run_subprocess(
            work_dir=project.dir,
            entry_point=entry_point,
            parameters=params,
            experiment_id=experiment_id,
            use_conda=use_conda,
            docker_args=docker_args,
            storage_dir=storage_dir,
            run_id=run_id,
        )


def _run_launch_cmd(cmd, env_map):
    """
    Invoke ``wandb launch`` in a subprocess, which in turn runs the entry point in a child process.
    Returns a handle to the subprocess. Popen launched to invoke ``wandb launch``.
    """
    final_env = os.environ.copy()
    final_env.update(env_map)
    # Launch `wandb launch` command as the leader of its own process group so that we can do a
    # best-effort cleanup of all its descendant processes if needed
    if sys.platform == "win32":
        return subprocess.Popen(
            cmd,
            env=final_env,
            universal_newlines=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    else:
        return subprocess.Popen(
            cmd, env=final_env, universal_newlines=True, preexec_fn=os.setsid
        )


def _run_entry_point(command, work_dir, experiment_id, run_id):
    """
    Run an entry point command in a subprocess, returning a SubmittedRun that can be used to
    query the run's status.
    :param command: Entry point command to run
    :param work_dir: Working directory in which to run the command
    :param run: SubmittedRun object associated with the entry point execution.
    """
    env = os.environ.copy()
    env.update(get_run_env_vars(run_id))
    _logger.info("=== Running command '%s' in run with ID '%s' === ", command, run_id)
    # in case os name is not 'nt', we are not running on windows. It introduces
    # bash command otherwise.
    if os.name != "nt":
        process = subprocess.Popen(
            ["bash", "-c", command], close_fds=True, cwd=work_dir, env=env
        )
    else:
        # process = subprocess.Popen(command, close_fds=True, cwd=work_dir, env=env)
        process = subprocess.Popen(
            ["cmd", "/c", command], close_fds=True, cwd=work_dir, env=env
        )
    return LocalSubmittedRun(run_id, process)


def _invoke_wandb_run_subprocess(
    work_dir,
    entry_point,
    parameters,
    experiment_id,
    use_conda,
    docker_args,
    storage_dir,
    run_id,
):
    """
    Run an W&B project asynchronously by invoking ``wandb launch`` in a subprocess, returning
    a SubmittedRun that can be used to query run status.
    """
    _logger.info("=== Asynchronously launching W&B run with ID %s ===", run_id)
    wandb_run_arr = _build_wandb_run_cmd(
        uri=work_dir,
        entry_point=entry_point,
        docker_args=docker_args,
        storage_dir=storage_dir,
        use_conda=use_conda,
        run_id=run_id,
        parameters=parameters,
    )
    env_vars = get_run_env_vars(run_id)
    wandb_run_subprocess = _run_launch_cmd(wandb_run_arr, env_vars)
    return LocalSubmittedRun(run_id, wandb_run_subprocess)


def _build_wandb_run_cmd(
    uri, entry_point, docker_args, storage_dir, use_conda, run_id, parameters
):
    """
    Build and return an array containing an ``wandb launch`` command that can be invoked to locally
    run the project at the specified URI.
    """
    wandb_run_arr = ["wandb", "launch", uri, "-e", entry_point, "--run-id", run_id]
    if docker_args is not None:
        for key, value in docker_args.items():
            args = key if isinstance(value, bool) else "%s=%s" % (key, value)
            wandb_run_arr.extend(["--docker-args", args])
    if storage_dir is not None:
        wandb_run_arr.extend(["--storage-dir", storage_dir])
    if not use_conda:
        wandb_run_arr.append("--no-conda")
    for key, value in parameters.items():
        wandb_run_arr.extend(["-P", "%s=%s" % (key, value)])
    return wandb_run_arr


def _get_docker_command(
    image, run_id, docker_args=None, volumes=None, user_env_vars=None
):
    docker_path = "docker"
    cmd = [docker_path, "run", "--rm"]
    # cmd = [docker_path, "run"]      # todo debug -- we should probably add the option to not rm for the user to debug

    if docker_args:
        for name, value in docker_args.items():
            # Passed just the name as boolean flag
            if isinstance(value, bool) and value:
                if len(name) == 1:
                    cmd += ["-" + name]
                else:
                    cmd += ["--" + name]
            else:
                # Passed name=value
                if len(name) == 1:
                    cmd += ["-" + name, value]
                else:
                    cmd += ["--" + name, value]

    env_vars = {}  # TODO: get these from elsewhere?
    if user_env_vars is not None:
        for user_entry in user_env_vars:
            if isinstance(user_entry, list):
                # User has defined a new environment variable for the docker environment
                env_vars[user_entry[0]] = user_entry[1]
            else:
                # User wants to copy an environment variable from system environment
                system_var = os.environ.get(user_entry)
                if system_var is None:
                    raise ExecutionException(
                        "This project expects the %s environment variables to "
                        "be set on the machine running the project, but %s was "
                        "not set. Please ensure all expected environment variables "
                        "are set" % (", ".join(user_env_vars), user_entry)
                    )
                env_vars[user_entry] = system_var

    if volumes is not None:
        for v in volumes:
            cmd += ["-v", v]

    for key, value in env_vars.items():
        cmd += ["-e", "{key}={value}".format(key=key, value=value)]
    cmd += [image.tags[0]]
    return cmd


def _get_local_artifact_cmd_and_envs(uri):
    artifact_dir = os.path.dirname(uri)
    container_path = artifact_dir
    if not os.path.isabs(container_path):
        container_path = os.path.join(WANDB_DOCKER_WORKDIR_PATH, container_path)
        container_path = os.path.normpath(container_path)
    abs_artifact_dir = os.path.abspath(artifact_dir)
    return ["-v", "%s:%s" % (abs_artifact_dir, container_path)], {}


def _get_s3_artifact_cmd_and_envs():
    # pylint: disable=unused-argument
    if platform.system() == "Windows":
        win_user_dir = os.environ["USERPROFILE"]
        aws_path = os.path.join(win_user_dir, ".aws")
    else:
        aws_path = posixpath.expanduser("~/.aws")

    volumes = []
    if posixpath.exists(aws_path):
        volumes = ["-v", "%s:%s" % (str(aws_path), "/.aws")]
    envs = {
        "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY"),
        "AWS_ACCESS_KEY_ID": os.environ.get("AWS_ACCESS_KEY_ID"),
        "AWS_S3_ENDPOINT_URL": os.environ.get("AWS_S3_ENDPOINT_URL"),
        "AWS_S3_IGNORE_TLS": os.environ.get("AWS_S3_IGNORE_TLS"),
    }
    envs = dict((k, v) for k, v in envs.items() if v is not None)
    return volumes, envs


def _get_azure_blob_artifact_cmd_and_envs():
    # pylint: disable=unused-argument
    envs = {
        "AZURE_STORAGE_CONNECTION_STRING": os.environ.get(
            "AZURE_STORAGE_CONNECTION_STRING"
        ),
        "AZURE_STORAGE_ACCESS_KEY": os.environ.get("AZURE_STORAGE_ACCESS_KEY"),
    }
    envs = dict((k, v) for k, v in envs.items() if v is not None)
    return [], envs


def _get_gcs_artifact_cmd_and_envs():
    # pylint: disable=unused-argument
    cmds = []
    envs = {}

    if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
        credentials_path = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
        cmds = ["-v", "{}:/.gcs".format(credentials_path)]
        envs["GOOGLE_APPLICATION_CREDENTIALS"] = "/.gcs"
    return cmds, envs


def _get_docker_artifact_storage_cmd_and_envs(artifact_uri):
    if artifact_uri.startswith("gs:"):
        return _get_gcs_artifact_cmd_and_envs()
    elif artifact_uri.startswith("s3:"):
        return _get_s3_artifact_cmd_and_envs()
    elif artifact_uri.startswith("az:"):
        return _get_azure_blob_artifact_cmd_and_envs()
    else:
        return _get_local_artifact_cmd_and_envs()
