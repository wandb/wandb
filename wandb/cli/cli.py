import wandb

import click
from functools import wraps


#CONTEXT = dict(default_map=api.settings())
CONTEXT = dict(default_map={})


def display_error(func):
    """Function decorator for catching common errors and re-raising as wandb.Error"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except wandb.Error as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            lines = traceback.format_exception(
                exc_type, exc_value, exc_traceback)
            logger.error(''.join(lines))
            click_exc = ClickWandbException(e)
            click_exc.orig_type = exc_type
            six.reraise(ClickWandbException, click_exc, sys.exc_info()[2])
    return wrapper


class RunGroup(click.Group):
    @display_error
    def get_command(self, ctx, cmd_name):
        # TODO: check if cmd_name is a file in the current dir and not require `run`?
        rv = click.Group.get_command(self, ctx, cmd_name)
        if rv is not None:
            return rv
        return None


@click.command(cls=RunGroup, invoke_without_command=True)
@click.version_option(version=wandb.__version__)
@click.pass_context
def cli(ctx):
    #wandb.try_to_set_up_global_logging()
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command(context_settings=CONTEXT, help="Login to Weights & Biases")
@display_error
def login():
    wandb.login()


@cli.command(context_settings=CONTEXT, help="Run a SUPER agent", hidden=True)
@click.option("--project", "-p", default=None, help="The project use.")
@click.option("--entity", "-e", default=None, help="The entity to use.")
@click.argument('agent_spec', nargs=-1)
@display_error
def agent(project=None, entity=None, agent_spec=None):
    wandb.agent.run_agent(agent_spec)
