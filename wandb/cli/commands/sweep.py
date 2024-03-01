import os

import click

import wandb
from wandb import util, wandb_agent, wandb_sdk
from wandb.cli.commands.login import login
from wandb.cli.utils.api import _get_cling_api
from wandb.cli.utils.errors import display_error
from wandb.sdk.launch.sweeps import utils as sweep_utils


@click.command(
    name="agent",
    context_settings={"default_map": {}},
    help="Run the W&B agent",
)
@click.pass_context
@click.option(
    "--project",
    "-p",
    default=None,
    help="""The name of the project where W&B runs created from the sweep are sent to. If the project is not specified, the run is sent to a project labeled 'Uncategorized'.""",
)
@click.option(
    "--entity",
    "-e",
    default=None,
    help="""The username or team name where you want to send W&B runs created by the sweep to. Ensure that the entity you specify already exists. If you don't specify an entity, the run will be sent to your default entity, which is usually your username.""",
)
@click.option(
    "--count", default=None, type=int, help="The max number of runs for this agent."
)
@click.argument("sweep_id")
@display_error
def agent(ctx, project, entity, count, sweep_id):
    api = _get_cling_api()
    if api.api_key is None:
        wandb.termlog("Login to W&B to use the sweep agent feature")
        ctx.invoke(login, no_offline=True)
        api = _get_cling_api(reset=True)

    wandb.termlog("Starting wandb agent 🕵️")
    wandb_agent.agent(sweep_id, entity=entity, project=project, count=count)

    # you can send local commands like so:
    # agent_api.command({'type': 'run', 'program': 'train.py',
    #                'args': ['--max_epochs=10']})


@click.command(
    name="sweep",
    context_settings={"default_map": {}},
    help="Initialize a hyperparameter sweep. Search for hyperparameters that optimizes a cost function of a machine learning model by testing various combinations.",
)
@click.option(
    "--project",
    "-p",
    default=None,
    help="""The name of the project where W&B runs created from the sweep are sent to. If the project is not specified, the run is sent to a project labeled Uncategorized.""",
)
@click.option(
    "--entity",
    "-e",
    default=None,
    help="""The username or team name where you want to send W&B runs created by the sweep to. Ensure that the entity you specify already exists. If you don't specify an entity, the run will be sent to your default entity, which is usually your username.""",
)
@click.option("--controller", is_flag=True, default=False, help="Run local controller")
@click.option("--verbose", is_flag=True, default=False, help="Display verbose output")
@click.option(
    "--name",
    default=None,
    help="The name of the sweep. The sweep ID is used if no name is specified.",
)
@click.option("--program", default=None, help="Set sweep program")
@click.option("--settings", default=None, help="Set sweep settings", hidden=True)
@click.option("--update", default=None, help="Update pending sweep")
@click.option(
    "--stop",
    is_flag=True,
    default=False,
    help="Finish a sweep to stop running new runs and let currently running runs finish.",
)
@click.option(
    "--cancel",
    is_flag=True,
    default=False,
    help="Cancel a sweep to kill all running runs and stop running new runs.",
)
@click.option(
    "--pause",
    is_flag=True,
    default=False,
    help="Pause a sweep to temporarily stop running new runs.",
)
@click.option(
    "--resume",
    is_flag=True,
    default=False,
    help="Resume a sweep to continue running new runs.",
)
@click.argument("config_yaml_or_sweep_id")
@click.pass_context
@display_error
def sweep(
    ctx,
    project,
    entity,
    controller,
    verbose,
    name,
    program,
    settings,
    update,
    stop,
    cancel,
    pause,
    resume,
    config_yaml_or_sweep_id,
):
    state_args = "stop", "cancel", "pause", "resume"
    lcls = locals()
    is_state_change_command = sum(lcls[k] for k in state_args)
    if is_state_change_command > 1:
        raise Exception("Only one state flag (stop/cancel/pause/resume) is allowed.")
    elif is_state_change_command == 1:
        sweep_id = config_yaml_or_sweep_id
        api = _get_cling_api()
        if api.api_key is None:
            wandb.termlog("Login to W&B to use the sweep feature")
            ctx.invoke(login, no_offline=True)
            api = _get_cling_api(reset=True)
        parts = dict(entity=entity, project=project, name=sweep_id)
        err = sweep_utils.parse_sweep_id(parts)
        if err:
            wandb.termerror(err)
            return
        entity = parts.get("entity") or entity
        project = parts.get("project") or project
        sweep_id = parts.get("name") or sweep_id
        state = [s for s in state_args if lcls[s]][0]
        ings = {
            "stop": "Stopping",
            "cancel": "Cancelling",
            "pause": "Pausing",
            "resume": "Resuming",
        }
        wandb.termlog(f"{ings[state]} sweep {entity}/{project}/{sweep_id}")
        getattr(api, "%s_sweep" % state)(sweep_id, entity=entity, project=project)
        wandb.termlog("Done.")
        return
    else:
        config_yaml = config_yaml_or_sweep_id

    def _parse_settings(settings):
        """Parse settings from json or comma separated assignments."""
        ret = {}
        # TODO(jhr): merge with magic:_parse_magic
        if settings.find("=") > 0:
            for item in settings.split(","):
                kv = item.split("=")
                if len(kv) != 2:
                    wandb.termwarn(
                        "Unable to parse sweep settings key value pair", repeat=False
                    )
                ret.update(dict([kv]))
            return ret
        wandb.termwarn("Unable to parse settings parameter", repeat=False)
        return ret

    api = _get_cling_api()
    if api.api_key is None:
        wandb.termlog("Login to W&B to use the sweep feature")
        ctx.invoke(login, no_offline=True)
        api = _get_cling_api(reset=True)

    sweep_obj_id = None
    if update:
        parts = dict(entity=entity, project=project, name=update)
        err = sweep_utils.parse_sweep_id(parts)
        if err:
            wandb.termerror(err)
            return
        entity = parts.get("entity") or entity
        project = parts.get("project") or project
        sweep_id = parts.get("name") or update

        has_project = (project or api.settings("project")) is not None
        has_entity = (entity or api.settings("entity")) is not None

        termerror_msg = (
            "Sweep lookup requires a valid %s, and none was specified. \n"
            "Either set a default %s in wandb/settings, or, if invoking \n`wandb sweep` "
            "from the command line, specify the full sweep path via: \n\n"
            "    wandb sweep {username}/{projectname}/{sweepid}\n\n"
        )

        if not has_entity:
            wandb.termerror(termerror_msg % (("entity",) * 2))
            return

        if not has_project:
            wandb.termerror(termerror_msg % (("project",) * 2))
            return

        found = api.sweep(sweep_id, "{}", entity=entity, project=project)
        if not found:
            wandb.termerror(f"Could not find sweep {entity}/{project}/{sweep_id}")
            return
        sweep_obj_id = found["id"]

    action = "Updating" if sweep_obj_id else "Creating"
    wandb.termlog(f"{action} sweep from: {config_yaml}")
    config = sweep_utils.load_sweep_config(config_yaml)

    # Set or override parameters
    if name:
        config["name"] = name
    if program:
        config["program"] = program
    if settings:
        settings = _parse_settings(settings)
        if settings:
            config.setdefault("settings", {})
            config["settings"].update(settings)
    if controller:
        config.setdefault("controller", {})
        config["controller"]["type"] = "local"

    is_local = config.get("controller", {}).get("type") == "local"
    if is_local:
        from wandb import controller as wandb_controller

        tuner = wandb_controller()
        err = tuner._validate(config)
        if err:
            wandb.termerror(f"Error in sweep file: {err}")
            return

    env = os.environ
    entity = (
        entity
        or env.get("WANDB_ENTITY")
        or config.get("entity")
        or api.settings("entity")
    )
    project = (
        project
        or env.get("WANDB_PROJECT")
        or config.get("project")
        or api.settings("project")
        or util.auto_project_name(config.get("program"))
    )

    sweep_id, warnings = api.upsert_sweep(
        config,
        project=project,
        entity=entity,
        obj_id=sweep_obj_id,
    )
    sweep_utils.handle_sweep_config_violations(warnings)

    # Log nicely formatted sweep information
    styled_id = click.style(sweep_id, fg="yellow")
    wandb.termlog(f"{action} sweep with ID: {styled_id}")

    sweep_url = wandb_sdk.wandb_sweep._get_sweep_url(api, sweep_id)
    if sweep_url:
        styled_url = click.style(sweep_url, underline=True, fg="blue")
        wandb.termlog(f"View sweep at: {styled_url}")

    # re-probe entity and project if it was auto-detected by upsert_sweep
    entity = entity or env.get("WANDB_ENTITY")
    project = project or env.get("WANDB_PROJECT")

    if entity and project:
        sweep_path = f"{entity}/{project}/{sweep_id}"
    elif project:
        sweep_path = f"{project}/{sweep_id}"
    else:
        sweep_path = sweep_id

    if sweep_path.find(" ") >= 0:
        sweep_path = f"{sweep_path!r}"

    styled_path = click.style(f"wandb agent {sweep_path}", fg="yellow")
    wandb.termlog(f"Run sweep agent with: {styled_path}")
    if controller:
        wandb.termlog("Starting wandb controller...")
        from wandb import controller as wandb_controller

        tuner = wandb_controller(sweep_id)
        tuner.run(verbose=verbose)


@click.command(
    name="controller",
    context_settings={"default_map": {}},
    help="Run the W&B local sweep controller",
)
@click.option("--verbose", is_flag=True, default=False, help="Display verbose output")
@click.argument("sweep_id")
@display_error
def controller(verbose, sweep_id):
    click.echo("Starting wandb controller...")
    from wandb import controller as wandb_controller

    tuner = wandb_controller(sweep_id)
    tuner.run(verbose=verbose)
