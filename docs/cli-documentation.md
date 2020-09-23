---
menu: main
title: CLI Documentation
---

<a name="wandb.cli.cli"></a>
# wandb.cli.cli

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/cli/cli.py#L4)

<a name="wandb.cli.cli.display_error"></a>
#### display\_error

```python
display_error(func)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/cli/cli.py#L56)

Function decorator for catching common errors and re-raising as wandb.Error

<a name="wandb.cli.cli.prompt_for_project"></a>
#### prompt\_for\_project

```python
prompt_for_project(ctx, entity)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/cli/cli.py#L81)

Ask the user for a project, creating one if necessary.

<a name="wandb.cli.cli.docker_run"></a>
#### docker\_run

```python
@cli.command(context_settings=RUN_CONTEXT, name="docker-run")
@click.pass_context
@click.argument('docker_run_args', nargs=-1)
@click.option('--help', is_flag=True)
docker_run(ctx, docker_run_args, help)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/cli/cli.py#L492)

Simple wrapper for `docker run` which sets W&B environment
Adds WANDB_API_KEY and WANDB_DOCKER to any docker run command.
This will also set the runtime to nvidia if the nvidia-docker executable is present on the system
and --runtime wasn't set.

<a name="wandb.cli.cli.docker"></a>
#### docker

```python
@cli.command(context_settings=RUN_CONTEXT)
@click.pass_context
@click.argument('docker_run_args', nargs=-1)
@click.argument('docker_image', required=False)
@click.option('--nvidia/--no-nvidia', default=find_executable('nvidia-docker') is not None,
              help='Use the nvidia runtime, defaults to nvidia if nvidia-docker is present')
@click.option('--digest', is_flag=True, default=False, help="Output the image digest and exit")
@click.option('--jupyter/--no-jupyter', default=False, help="Run jupyter lab in the container")
@click.option('--dir', default="/app", help="Which directory to mount the code in the container")
@click.option('--no-dir', is_flag=True, help="Don't mount the current directory")
@click.option('--shell', default="/bin/bash", help="The shell to start the container with")
@click.option('--port', default="8888", help="The host port to bind jupyter on")
@click.option('--cmd', help="The command to run in the container")
@click.option('--no-tty', is_flag=True, default=False, help="Run the command without a tty")
@display_error
docker(ctx, docker_run_args, docker_image, nvidia, digest, jupyter, dir, no_dir, shell, port, cmd, no_tty)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/cli/cli.py#L541)

W&B docker lets you run your code in a docker image ensuring wandb is configured. It adds the WANDB_DOCKER and WANDB_API_KEY
environment variables to your container and mounts the current directory in /app by default.  You can pass additional
args which will be added to `docker run` before the image name is declared, we'll choose a default image for you if
one isn't passed:

wandb docker -v /mnt/dataset:/app/data
wandb docker gcr.io/kubeflow-images-public/tensorflow-1.12.0-notebook-cpu:v0.4.0 --jupyter
wandb docker wandb/deepo:keras-gpu --no-tty --cmd "python train.py --epochs=5"

By default we override the entrypoint to check for the existance of wandb and install it if not present.  If you pass the --jupyter
flag we will ensure jupyter is installed and start jupyter lab on port 8888.  If we detect nvidia-docker on your system we will use
the nvidia runtime.  If you just want wandb to set environment variable to an existing docker run command, see the wandb docker-run
command.

