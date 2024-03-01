import os
import sys

import click

from wandb.cli.utils.errors import display_error
from wandb.integration.magic import magic_install


@click.command(
    name="magic",
    context_settings={"default_map": {}},
    hidden=True,
    help="Run any script with wandb",
)
@click.pass_context
@click.argument("program")
@click.argument("args", nargs=-1)
@display_error
def magic(ctx, program, args):
    def magic_run(cmd, globals, locals):
        try:
            exec(cmd, globals, locals)
        finally:
            pass

    sys.argv[:] = args
    sys.argv.insert(0, program)
    sys.path.insert(0, os.path.dirname(program))
    try:
        with open(program, "rb") as fp:
            code = compile(fp.read(), program, "exec")
    except OSError:
        click.echo(click.style("Could not launch program: %s" % program, fg="red"))
        sys.exit(1)
    globs = {
        "__file__": program,
        "__name__": "__main__",
        "__package__": None,
        "wandb_magic_install": magic_install,
    }
    prep = (
        """
        import __main__
        __main__.__file__ = "%s"
        wandb_magic_install()
        """
        % program
    )
    magic_run(prep, globs, None)
    magic_run(code, globs, None)
