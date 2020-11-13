# display_error
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/cli/cli.py#L80-L95)

`def display_error(func):`

Function decorator for catching common errors and re-raising as wandb.Error











# _get_cling_api
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/cli/cli.py#L101-L111)

`def _get_cling_api(reset=None):`

Get a reference to the internal api with cling settings.











# prompt_for_project
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/cli/cli.py#L114-L148)

`def prompt_for_project(ctx, entity):`

Ask the user for a project, creating one if necessary.











# docker_run
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/cli/cli.py#L828-L869)

`def docker_run(ctx, docker_run_args, help):`

Simple wrapper for `docker run` which sets W&B environment
Adds WANDB_API_KEY and WANDB_DOCKER to any docker run command.
This will also set the runtime to nvidia if the nvidia-docker executable is present on the system
and --runtime wasn't set.












# docker
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/cli/cli.py#L872-L1003)

`def docker( ctx, docker_run_args, docker_image, nvidia, digest, jupyter, dir, no_dir, shell, port, cmd, no_tty, ):`

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












