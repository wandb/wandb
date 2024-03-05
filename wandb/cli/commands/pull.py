import os
import sys

import click

from wandb import env
from wandb.apis import InternalApi
from wandb.cli.utils.errors import ClickException, display_error
from wandb.sdk.lib import filesystem


@click.command(
    name="pull",
    context_settings={"default_map": {}},
    help="Pull files from Weights & Biases",
)
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
def pull(run, project, entity):
    api = InternalApi()
    project, run = api.parse_slug(run, project=project)
    urls = api.download_urls(project, run=run, entity=entity)
    if len(urls) == 0:
        raise ClickException("Run has no files")
    click.echo(f"Downloading: {click.style(project, bold=True)}/{run}")

    for name in urls:
        if api.file_current(name, urls[name]["md5"]):
            click.echo("File %s is up to date" % name)
        else:
            length, response = api.download_file(urls[name]["url"])
            # TODO: I had to add this because some versions in CI broke click.progressbar
            sys.stdout.write("File %s\r" % name)
            dirname = os.path.dirname(name)
            if dirname != "":
                filesystem.mkdir_exists_ok(dirname)
            with click.progressbar(
                length=length,
                label="File %s" % name,
                fill_char=click.style("&", fg="green"),
            ) as bar:
                with open(name, "wb") as f:
                    for data in response.iter_content(chunk_size=4096):
                        f.write(data)
                        bar.update(len(data))
