import os
import sys
import textwrap

import click
from click import ClickException

import wandb
import wandb.env as env
from wandb import util
from wandb.apis import InternalApi
from wandb.cli.commands.login import login
from wandb.cli.utils.api import _get_cling_api
from wandb.cli.utils.errors import ClickWandbException, display_error
from wandb.sdk.lib import filesystem


@click.command(
    name="init",
    context_settings={"default_map": {}},
    help="Configure a directory with Weights & Biases",
)
@click.option("--project", "-p", help="The project to use.")
@click.option("--entity", "-e", help="The entity to scope the project to.")
# TODO(jhr): Enable these with settings rework
# @click.option("--setting", "-s", help="enable an arbitrary setting.", multiple=True)
# @click.option('--show', is_flag=True, help="Show settings")
@click.option("--reset", is_flag=True, help="Reset settings")
@click.option(
    "--mode",
    "-m",
    help='Can be "online", "offline" or "disabled". Defaults to online.',
)
@click.pass_context
@display_error
def init(ctx, project, entity, reset, mode):
    from wandb.old.core import __stage_dir__, _set_stage_dir, wandb_dir

    if __stage_dir__ is None:
        _set_stage_dir("wandb")

    # non-interactive init
    if reset or project or entity or mode:
        api = InternalApi()
        if reset:
            api.clear_setting("entity", persist=True)
            api.clear_setting("project", persist=True)
            api.clear_setting("mode", persist=True)
            # TODO(jhr): clear more settings?
        if entity:
            api.set_setting("entity", entity, persist=True)
        if project:
            api.set_setting("project", project, persist=True)
        if mode:
            api.set_setting("mode", mode, persist=True)
        return

    if os.path.isdir(wandb_dir()) and os.path.exists(
        os.path.join(wandb_dir(), "settings")
    ):
        click.confirm(
            click.style(
                "This directory has been configured previously, should we re-configure it?",
                bold=True,
            ),
            abort=True,
        )
    else:
        click.echo(
            click.style("Let's setup this directory for W&B!", fg="green", bold=True)
        )
    api = _get_cling_api()
    if api.api_key is None:
        ctx.invoke(login)
        api = _get_cling_api(reset=True)

    viewer = api.viewer()

    # Viewer can be `None` in case your API information became invalid, or
    # in testing if you switch hosts.
    if not viewer:
        click.echo(
            click.style(
                "Your login information seems to be invalid: can you log in again please?",
                fg="red",
                bold=True,
            )
        )
        ctx.invoke(login)
        api = _get_cling_api(reset=True)

    # This shouldn't happen.
    viewer = api.viewer()
    if not viewer:
        click.echo(
            click.style(
                "We're sorry, there was a problem logging you in. "
                "Please send us a note at support@wandb.com and tell us how this happened.",
                fg="red",
                bold=True,
            )
        )
        sys.exit(1)

    # At this point we should be logged in successfully.
    if len(viewer["teams"]["edges"]) > 1:
        team_names = [e["node"]["name"] for e in viewer["teams"]["edges"]] + [
            "Manual entry"
        ]
        wandb.termlog(
            "Which team should we use?",
        )
        result = util.prompt_choices(team_names)
        # result can be empty on click
        if result:
            entity = result
        else:
            entity = "Manual Entry"
        if entity == "Manual Entry":
            entity = click.prompt("Enter the name of the team you want to use")
    else:
        entity = viewer.get("entity") or click.prompt(
            "What username or team should we use?"
        )

    # TODO: this error handling sucks and the output isn't pretty
    try:
        project = prompt_for_project(ctx, entity)
    except ClickWandbException:
        raise ClickException(f"Could not find team: {entity}")

    api.set_setting("entity", entity, persist=True)
    api.set_setting("project", project, persist=True)
    api.set_setting("base_url", api.settings().get("base_url"), persist=True)

    filesystem.mkdir_exists_ok(wandb_dir())
    with open(os.path.join(wandb_dir(), ".gitignore"), "w") as file:
        file.write("*\n!settings")

    click.echo(
        click.style("This directory is configured!  Next, track a run:\n", fg="green")
        + textwrap.dedent(
            """\
        * In your training script:
            {code1}
            {code2}
        * then `{run}`.
        """
        ).format(
            code1=click.style("import wandb", bold=True),
            code2=click.style('wandb.init(project="%s")' % project, bold=True),
            run=click.style("python <train.py>", bold=True),
        )
    )


@click.command(
    name="projects",
    context_settings={"default_map": {}},
    help="List projects",
    hidden=True,
)
@click.option(
    "--entity",
    "-e",
    default=None,
    envvar=env.ENTITY,
    help="The entity to scope the listing to.",
)
@display_error
def projects(entity, display=True):
    api = _get_cling_api()
    projects = api.list_projects(entity=entity)
    if len(projects) == 0:
        message = "No projects found for %s" % entity
    else:
        message = 'Latest projects for "%s"' % entity
    if display:
        click.echo(click.style(message, bold=True))
        for project in projects:
            click.echo(
                "".join(
                    (
                        click.style(project["name"], fg="blue", bold=True),
                        " - ",
                        str(project["description"] or "").split("\n")[0],
                    )
                )
            )
    return projects


def prompt_for_project(ctx, entity):
    """Ask the user for a project, creating one if necessary."""
    result = ctx.invoke(projects, entity=entity, display=False)
    api = _get_cling_api()
    try:
        if len(result) == 0:
            project = click.prompt("Enter a name for your first project")
            # description = editor()
            project = api.upsert_project(project, entity=entity)["name"]
        else:
            project_names = [project["name"] for project in result] + ["Create New"]
            wandb.termlog("Which project should we use?")
            result = util.prompt_choices(project_names)
            if result:
                project = result
            else:
                project = "Create New"
            # TODO: check with the server if the project exists
            if project == "Create New":
                project = click.prompt(
                    "Enter a name for your new project", value_proc=api.format_project
                )
                # description = editor()
                project = api.upsert_project(project, entity=entity)["name"]

    except wandb.errors.CommError as e:
        raise ClickException(str(e))

    return project
