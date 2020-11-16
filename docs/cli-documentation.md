---
title: CLI Documentation
---

<a name="wandb.cli.cli"></a>
# wandb.cli.cli

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L4)

<a name="wandb.cli.cli.whaaaaat"></a>
#### whaaaaat

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L42)

<a name="wandb.cli.cli.logger"></a>
#### logger

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L55)

<a name="wandb.cli.cli.CONTEXT"></a>
#### CONTEXT

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L57)

<a name="wandb.cli.cli.cli_unsupported"></a>
#### cli\_unsupported

```python
cli_unsupported(argument)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L60)

<a name="wandb.cli.cli.ClickWandbException"></a>
## ClickWandbException Objects

```python
class ClickWandbException(ClickException)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L65)

<a name="wandb.cli.cli.ClickWandbException.format_message"></a>
#### format\_message

```python
 | format_message()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L66)

<a name="wandb.cli.cli.display_error"></a>
#### display\_error

```python
display_error(func)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L80)

Function decorator for catching common errors and re-raising as wandb.Error

<a name="wandb.cli.cli.prompt_for_project"></a>
#### prompt\_for\_project

```python
prompt_for_project(ctx, entity)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L114)

Ask the user for a project, creating one if necessary.

<a name="wandb.cli.cli.RunGroup"></a>
## RunGroup Objects

```python
class RunGroup(click.Group)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L151)

<a name="wandb.cli.cli.RunGroup.get_command"></a>
#### get\_command

```python
 | @display_error
 | get_command(ctx, cmd_name)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L153)

<a name="wandb.cli.cli.cli"></a>
#### cli

```python
@click.command(cls=RunGroup, invoke_without_command=True)
@click.version_option(version=wandb.__version__)
@click.pass_context
cli(ctx)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L164)

<a name="wandb.cli.cli.projects"></a>
#### projects

```python
@cli.command(context_settings=CONTEXT, help="List projects", hidden=True)
@click.option(
    "--entity",
    "-e",
    default=None,
    envvar=env.ENTITY,
    help="The entity to scope the listing to.",
)
@display_error
projects(entity, display=True)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L179)

<a name="wandb.cli.cli.login"></a>
#### login

```python
@cli.command(context_settings=CONTEXT, help="Login to Weights & Biases")
@click.argument("key", nargs=-1)
@click.option("--cloud", is_flag=True, help="Login to the cloud instead of local")
@click.option("--host", default=None, help="Login to a specific instance of W&B")
@click.option(
    "--relogin", default=None, is_flag=True, help="Force relogin if already logged in."
)
@click.option("--anonymously", default=False, is_flag=True, help="Log in anonymously")
@display_error
login(key, host, cloud, relogin, anonymously, no_offline=False)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L210)

<a name="wandb.cli.cli.grpc_server"></a>
#### grpc\_server

```python
@cli.command(
    context_settings=CONTEXT, help="Run a grpc server", name="grpc-server", hidden=True
)
@display_error
grpc_server(project=None, entity=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L246)

<a name="wandb.cli.cli.superagent"></a>
#### superagent

```python
@cli.command(context_settings=CONTEXT, help="Run a SUPER agent", hidden=True)
@click.option("--project", "-p", default=None, help="The project use.")
@click.option("--entity", "-e", default=None, help="The entity to use.")
@click.argument("agent_spec", nargs=-1)
@display_error
superagent(project=None, entity=None, agent_spec=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L261)

<a name="wandb.cli.cli.init"></a>
#### init

```python
@cli.command(
    context_settings=CONTEXT, help="Configure a directory with Weights & Biases"
)
@click.option("--project", "-p", help="The project to use.")
@click.option("--entity", "-e", help="The entity to scope the project to.")
@click.option("--reset", is_flag=True, help="Reset settings")
@click.option(
    "--mode",
    "-m",
    help=' Can be "online", "offline" or "disabled". Defaults to online.',
)
@click.pass_context
@display_error
init(ctx, project, entity, reset, mode)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L281)

<a name="wandb.cli.cli.sync"></a>
#### sync

```python
@cli.command(
    context_settings=CONTEXT, help="Upload an offline training directory to W&B"
)
@click.pass_context
@click.argument("path", nargs=-1, type=click.Path(exists=True))
@click.option("--view", is_flag=True, default=False, help="View runs", hidden=True)
@click.option("--verbose", is_flag=True, default=False, help="Verbose", hidden=True)
@click.option("--id", "run_id", help="The run you want to upload to.")
@click.option("--project", "-p", help="The project you want to upload to.")
@click.option("--entity", "-e", help="The entity to scope to.")
@click.option("--include-globs", help="Comma seperated list of globs to include.")
@click.option("--exclude-globs", help="Comma seperated list of globs to exclude.")
@click.option(
    "--include-online/--no-include-online",
    is_flag=True,
    default=None,
    help="Include online runs",
)
@click.option(
    "--include-offline/--no-include-offline",
    is_flag=True,
    default=None,
    help="Include offline runs",
)
@click.option(
    "--include-synced/--no-include-synced",
    is_flag=True,
    default=None,
    help="Include synced runs",
)
@click.option(
    "--mark-synced/--no-mark-synced",
    is_flag=True,
    default=True,
    help="Mark runs as synced",
)
@click.option("--sync-all", is_flag=True, default=False, help="Sync all runs")
@click.option("--clean", is_flag=True, default=False, help="Delete synced runs")
@click.option(
    "--clean-old-hours",
    default=24,
    help="Delete runs created before this many hours. To be used alongside --clean flag.",
    type=int,
)
@click.option(
    "--clean-force",
    is_flag=True,
    default=False,
    help="Clean without confirmation prompt.",
)
@click.option("--ignore", hidden=True)
@click.option("--show", default=5, help="Number of runs to show")
@display_error
sync(ctx, path=None, view=None, verbose=None, run_id=None, project=None, entity=None, include_globs=None, exclude_globs=None, include_online=None, include_offline=None, include_synced=None, mark_synced=None, sync_all=None, ignore=None, show=None, clean=None, clean_old_hours=24, clean_force=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L457)

<a name="wandb.cli.cli.sweep"></a>
#### sweep

```python
@cli.command(context_settings=CONTEXT, help="Create a sweep")  # noqa: C901
@click.pass_context
@click.option("--project", "-p", default=None, help="The project of the sweep.")
@click.option("--entity", "-e", default=None, help="The entity scope for the project.")
@click.option("--controller", is_flag=True, default=False, help="Run local controller")
@click.option("--verbose", is_flag=True, default=False, help="Display verbose output")
@click.option("--name", default=False, help="Set sweep name")
@click.option("--program", default=False, help="Set sweep program")
@click.option("--settings", default=False, help="Set sweep settings", hidden=True)
@click.option("--update", default=None, help="Update pending sweep")
@click.argument("config_yaml")
@display_error
sweep(ctx, project, entity, controller, verbose, name, program, settings, update, config_yaml)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L641)

<a name="wandb.cli.cli.agent"></a>
#### agent

```python
@cli.command(context_settings=CONTEXT, help="Run the W&B agent")
@click.pass_context
@click.option("--project", "-p", default=None, help="The project of the sweep.")
@click.option("--entity", "-e", default=None, help="The entity scope for the project.")
@click.option(
    "--count", default=None, type=int, help="The max number of runs for this agent."
)
@click.argument("sweep_id")
@display_error
agent(ctx, project, entity, count, sweep_id)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L798)

<a name="wandb.cli.cli.controller"></a>
#### controller

```python
@cli.command(context_settings=CONTEXT, help="Run the W&B local sweep controller")
@click.option("--verbose", is_flag=True, default=False, help="Display verbose output")
@click.argument("sweep_id")
@display_error
controller(verbose, sweep_id)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L817)

<a name="wandb.cli.cli.RUN_CONTEXT"></a>
#### RUN\_CONTEXT

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L823)

<a name="wandb.cli.cli.RUN_CONTEXT["allow_extra_args"]"></a>
#### RUN\_CONTEXT["allow\_extra\_args"]

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L824)

<a name="wandb.cli.cli.RUN_CONTEXT["ignore_unknown_options"]"></a>
#### RUN\_CONTEXT["ignore\_unknown\_options"]

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L825)

<a name="wandb.cli.cli.docker_run"></a>
#### docker\_run

```python
@cli.command(context_settings=RUN_CONTEXT, name="docker-run")
@click.pass_context
@click.argument("docker_run_args", nargs=-1)
@click.option("--help", is_flag=True)
docker_run(ctx, docker_run_args, help)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L832)

Simple wrapper for `docker run` which sets W&B environment
Adds WANDB_API_KEY and WANDB_DOCKER to any docker run command.
This will also set the runtime to nvidia if the nvidia-docker executable is present on the system
and --runtime wasn't set.

<a name="wandb.cli.cli.docker"></a>
#### docker

```python
@cli.command(context_settings=RUN_CONTEXT)
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
docker(ctx, docker_run_args, docker_image, nvidia, digest, jupyter, dir, no_dir, shell, port, cmd, no_tty)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L900)

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

<a name="wandb.cli.cli.local"></a>
#### local

```python
@cli.command(
    context_settings=RUN_CONTEXT, help="Launch local W&B container (Experimental)"
)
@click.pass_context
@click.option("--port", "-p", default="8080", help="The host port to bind W&B local on")
@click.option(
    "--env", "-e", default=[], multiple=True, help="Env vars to pass to wandb/local"
)
@click.option(
    "--daemon/--no-daemon", default=True, help="Run or don't run in daemon mode"
)
@click.option(
    "--upgrade", is_flag=True, default=False, help="Upgrade to the most recent version"
)
@click.option(
    "--edge", is_flag=True, default=False, help="Run the bleading edge", hidden=True
)
@display_error
local(ctx, port, env, daemon, upgrade, edge)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L1024)

<a name="wandb.cli.cli.artifact"></a>
#### artifact

```python
@cli.group(help="Commands for interacting with artifacts")
artifact()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L1095)

<a name="wandb.cli.cli.put"></a>
#### put

```python
@artifact.command(context_settings=CONTEXT, help="Upload an artifact to wandb")
@click.argument("path")
@click.option(
    "--name", "-n", help="The name of the artifact to push: project/artifact_name"
)
@click.option("--description", "-d", help="A description of this artifact")
@click.option("--type", "-t", default="dataset", help="The type of the artifact")
@click.option(
    "--alias",
    "-a",
    default=["latest"],
    multiple=True,
    help="An alias to apply to this artifact",
)
@display_error
put(path, name, description, type, alias)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L1114)

<a name="wandb.cli.cli.get"></a>
#### get

```python
@artifact.command(context_settings=CONTEXT, help="Download an artifact from wandb")
@click.argument("path")
@click.option("--root", help="The directory you want to download the artifact to")
@click.option("--type", help="The type of artifact you are downloading")
@display_error
get(path, root, type)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L1185)

<a name="wandb.cli.cli.ls"></a>
#### ls

```python
@artifact.command(
    context_settings=CONTEXT, help="List all artifacts in a wandb project"
)
@click.argument("path")
@click.option("--type", "-t", help="The type of artifacts to list")
@display_error
ls(path, type)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L1219)

<a name="wandb.cli.cli.pull"></a>
#### pull

```python
@cli.command(context_settings=CONTEXT, help="Pull files from Weights & Biases")
@click.argument("run", envvar=env.RUN_ID)
@click.option(
    "--project", "-p", envvar=env.PROJECT, help="The project you want to download."
)
@click.option(
    "--entity",
    "-e",
    default="models",
    envvar=env.ENTITY,
    help="The entity to scope the listing to.",
)
@display_error
pull(run, project, entity)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L1262)

<a name="wandb.cli.cli.restore"></a>
#### restore

```python
@cli.command(
    context_settings=CONTEXT, help="Restore code, config and docker state for a run"
)
@click.pass_context
@click.argument("run", envvar=env.RUN_ID)
@click.option("--no-git", is_flag=True, default=False, help="Skupp")
@click.option(
    "--branch/--no-branch",
    default=True,
    help="Whether to create a branch or checkout detached",
)
@click.option(
    "--project", "-p", envvar=env.PROJECT, help="The project you wish to upload to."
)
@click.option(
    "--entity", "-e", envvar=env.ENTITY, help="The entity to scope the listing to."
)
@display_error
restore(ctx, run, no_git, branch, project, entity)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L1313)

<a name="wandb.cli.cli.magic"></a>
#### magic

```python
@cli.command(context_settings=CONTEXT, help="Run any script with wandb", hidden=True)
@click.pass_context
@click.argument("program")
@click.argument("args", nargs=-1)
@display_error
magic(ctx, program, args)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L1451)

<a name="wandb.cli.cli.online"></a>
#### online

```python
@cli.command("online", help="Enable W&B sync")
@display_error
online()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L1487)

<a name="wandb.cli.cli.offline"></a>
#### offline

```python
@cli.command("offline", help="Disable W&B sync")
@display_error
offline()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L1500)

<a name="wandb.cli.cli.on"></a>
#### on

```python
@cli.command("on", hidden=True)
@click.pass_context
@display_error
on(ctx)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L1516)

<a name="wandb.cli.cli.off"></a>
#### off

```python
@cli.command("off", hidden=True)
@click.pass_context
@display_error
off(ctx)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L1523)

<a name="wandb.cli.cli.status"></a>
#### status

```python
@cli.command("status", help="Show configuration settings")
@click.option(
    "--settings/--no-settings", help="Show the current settings", default=True
)
status(settings)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L1531)

<a name="wandb.cli.cli.disabled"></a>
#### disabled

```python
@cli.command("disabled", help="Disable W&B.")
disabled()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L1542)

<a name="wandb.cli.cli.enabled"></a>
#### enabled

```python
@cli.command("enabled", help="Enable W&B.")
enabled()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/cli/cli.py#L1554)

