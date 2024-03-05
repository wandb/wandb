import os
import subprocess
import sys

import click
from click import ClickException

# pycreds has a find_executable that works in windows
from dockerpycreds.utils import find_executable

import wandb
from wandb import util
from wandb.apis import InternalApi
from wandb.cli.utils.errors import display_error


@click.command(
    name="docker-run",
    context_settings={
        "default_map": {},
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
)
@click.pass_context
@click.argument("docker_run_args", nargs=-1)
def docker_run(ctx, docker_run_args):
    """Wrap `docker run` and adds WANDB_API_KEY and WANDB_DOCKER environment variables.

    This will also set the runtime to nvidia if the nvidia-docker executable is present
    on the system and --runtime wasn't set.

    See `docker run --help` for more details.
    """
    api = InternalApi()
    args = list(docker_run_args)
    if len(args) > 0 and args[0] == "run":
        args.pop(0)
    if len([a for a in args if a.startswith("--runtime")]) == 0 and find_executable(
        "nvidia-docker"
    ):
        args = ["--runtime", "nvidia"] + args
    #  TODO: image_from_docker_args uses heuristics to find the docker image arg, there are likely cases
    #  where this won't work
    image = util.image_from_docker_args(args)
    resolved_image = None
    if image:
        resolved_image = wandb.docker.image_id(image)
    if resolved_image:
        args = ["-e", "WANDB_DOCKER=%s" % resolved_image] + args
    else:
        wandb.termlog(
            "Couldn't detect image argument, running command without the WANDB_DOCKER env variable"
        )
    if api.api_key:
        args = ["-e", "WANDB_API_KEY=%s" % api.api_key] + args
    else:
        wandb.termlog(
            "Not logged in, run `wandb login` from the host machine to enable result logging"
        )
    subprocess.call(["docker", "run"] + args)


@click.command(
    name="docker",
    context_settings={
        "default_map": {},
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
)
@click.pass_context
@click.argument("docker_run_args", nargs=-1)
@click.argument("docker_image", required=False)
@click.option(
    "--nvidia/--no-nvidia",
    default=find_executable("nvidia-docker") is not None,
    help="Use the nvidia runtime, defaults to nvidia if nvidia-docker is present",
)
@click.option(
    "--digest", is_flag=True, default=False, help="Output the image digest and exit"
)
@click.option(
    "--jupyter/--no-jupyter", default=False, help="Run jupyter lab in the container"
)
@click.option(
    "--dir", default="/app", help="Which directory to mount the code in the container"
)
@click.option("--no-dir", is_flag=True, help="Don't mount the current directory")
@click.option(
    "--shell", default="/bin/bash", help="The shell to start the container with"
)
@click.option("--port", default="8888", help="The host port to bind jupyter on")
@click.option("--cmd", help="The command to run in the container")
@click.option(
    "--no-tty", is_flag=True, default=False, help="Run the command without a tty"
)
@display_error
def docker(
    ctx,
    docker_run_args,
    docker_image,
    nvidia,
    digest,
    jupyter,
    dir,
    no_dir,
    shell,
    port,
    cmd,
    no_tty,
):
    """Run your code in a docker container.

    W&B docker lets you run your code in a docker image ensuring wandb is configured. It
    adds the WANDB_DOCKER and WANDB_API_KEY environment variables to your container and
    mounts the current directory in /app by default.  You can pass additional args which
    will be added to `docker run` before the image name is declared, we'll choose a
    default image for you if one isn't passed:

    ```sh
    wandb docker -v /mnt/dataset:/app/data
    wandb docker gcr.io/kubeflow-images-public/tensorflow-1.12.0-notebook-cpu:v0.4.0 --jupyter
    wandb docker wandb/deepo:keras-gpu --no-tty --cmd "python train.py --epochs=5"
    ```

    By default, we override the entrypoint to check for the existence of wandb and
    install it if not present.  If you pass the --jupyter flag we will ensure jupyter is
    installed and start jupyter lab on port 8888.  If we detect nvidia-docker on your
    system we will use the nvidia runtime.  If you just want wandb to set environment
    variable to an existing docker run command, see the wandb docker-run command.
    """
    api = InternalApi()
    if not find_executable("docker"):
        raise ClickException("Docker not installed, install it from https://docker.com")
    args = list(docker_run_args)
    image = docker_image or ""
    # remove run for users used to nvidia-docker
    if len(args) > 0 and args[0] == "run":
        args.pop(0)
    if image == "" and len(args) > 0:
        image = args.pop(0)
    # If the user adds docker args without specifying an image (should be rare)
    if not util.docker_image_regex(image.split("@")[0]):
        if image:
            args = args + [image]
        image = wandb.docker.default_image(gpu=nvidia)
        subprocess.call(["docker", "pull", image])
    _, repo_name, tag = wandb.docker.parse(image)

    resolved_image = wandb.docker.image_id(image)
    if resolved_image is None:
        raise ClickException(
            "Couldn't find image locally or in a registry, try running `docker pull %s`"
            % image
        )
    if digest:
        sys.stdout.write(resolved_image)
        exit(0)

    existing = wandb.docker.shell(["ps", "-f", "ancestor=%s" % resolved_image, "-q"])
    if existing:
        if click.confirm(
            "Found running container with the same image, do you want to attach?"
        ):
            subprocess.call(["docker", "attach", existing.split("\n")[0]])
            exit(0)
    cwd = os.getcwd()
    command = [
        "docker",
        "run",
        "-e",
        "LANG=C.UTF-8",
        "-e",
        "WANDB_DOCKER=%s" % resolved_image,
        "--ipc=host",
        "-v",
        wandb.docker.entrypoint + ":/wandb-entrypoint.sh",
        "--entrypoint",
        "/wandb-entrypoint.sh",
    ]
    if nvidia:
        command.extend(["--runtime", "nvidia"])
    if not no_dir:
        #  TODO: We should default to the working directory if defined
        command.extend(["-v", cwd + ":" + dir, "-w", dir])
    if api.api_key:
        command.extend(["-e", "WANDB_API_KEY=%s" % api.api_key])
    else:
        wandb.termlog(
            "Couldn't find WANDB_API_KEY, run `wandb login` to enable streaming metrics"
        )
    if jupyter:
        command.extend(["-e", "WANDB_ENSURE_JUPYTER=1", "-p", port + ":8888"])
        no_tty = True
        cmd = (
            "jupyter lab --no-browser --ip=0.0.0.0 --allow-root --NotebookApp.token= --notebook-dir %s"
            % dir
        )
    command.extend(args)
    if no_tty:
        command.extend([image, shell, "-c", cmd])
    else:
        if cmd:
            command.extend(["-e", "WANDB_COMMAND=%s" % cmd])
        command.extend(["-it", image, shell])
        wandb.termlog("Launching docker container \U0001F6A2")
    subprocess.call(command)
