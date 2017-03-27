# -*- coding: utf-8 -*-

import click
from wandb import Api, Error
import random, time, os, re, netrc
from functools import wraps

def loggedIn(host):
    """Check if our host is in .netrc"""
    try:
        conf = netrc.netrc()
        return conf.hosts[host]
    except:
        return None

def login(host, entity, key):
    """Add our host and key to .netrc"""
    with open(os.path.expanduser('~/.netrc'), 'a') as f:
        f.write("""machine {host}
    login {entity}
    password {key}
""".format(host=host, entity=entity, key=key))

def display_error(func):
    """Function decorator for catching common errors and re-raising as wandb.Error"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Error as e:
            click.echo(click.style("ERROR! Something bad happened", fg="red")+
                       " {message}".format(message=e))
    return wrapper

api = Api()

@click.group()
@click.pass_context
def cli(context):
    """Console script for wandb"""
    context.default_map=api.config()

@cli.command()
@click.option("--entity", default="models", envvar='WANDB_ENTITY', help="The entity to scope the listing to.")
@display_error
def models(entity):
    click.echo(click.style('Latest models for entity "%s"' % entity, fg="blue", bold=True))
    for model in api.list_models():
        click.echo("".join(
            (click.style(model['name'], fg="blue", bold=True), 
            " - ", 
            model['description'].split("\n")[0])
        ))

@cli.command()
@click.option("--model", prompt=True, envvar='WANDB_MODEL', help="The model you wish to upload to.")
@click.argument("file", type=click.File('rb'))
@display_error
def upload(model, file):
    kind = "model" if re.search(r'(meta|json)$', file.name) else "weights"
    click.echo("Uploading model: {model}".format(
        model=click.style(model, bold=True)))
    url = api.upload_url(model, "%sUrl" % kind)
    length = os.fstat(file.fileno()).st_size
    with click.progressbar(length=length, label='Uploading %s' % kind,
                        fill_char=click.style('&', fg='green')) as bar:
        api.upload_file( url, file, lambda bites: bar.update(bites) )

@cli.command()     
@click.option("--model", prompt=True, envvar='WANDB_MODEL', help="The model to bump the version on.")  
@click.option("--description", default=None, help="A description of this revision")  
@click.option('--patch', 'part', flag_value='patch', default=True, help="Which version segment to increment")
@click.option('--minor', 'part', flag_value='minor')
@click.option('--major', 'part', flag_value='minor')
@display_error
def bump(model, description, part):
    rev = api.create_revision(model, description=description, part=part)
    click.echo("Bumped version to: %s" % rev['version'])

@cli.command()
@click.pass_context
@display_error
def init(ctx):
    click.echo(click.style("Let's setup this directory for W&B!", fg="green", bold=True))
    entity = click.prompt("What is your username?")
    ctx.invoke(models, entity=entity)
    host = api.config()['base_url'].split("/")[-1]
    if loggedIn(host) is None:
        key = click.prompt("{warning} Enter an api key from https://wandb.ai/profile to enable uploads".format(
            warning=click.style("Not authenticated!", fg="red"))
        )
        if key:
            login(host, entity, key)
    model = click.prompt("Enter a model name from above")
    with open(".wandb", "w") as file:
        file.write("[default]\nentity: {entity}\nmodel: {model}".format(entity=entity, model=model))
    click.echo(click.style("This directory is configured, run `wandb upload` to upload your model!", fg="green", bold=True))

@cli.command()
@click.option("--model", prompt=True, envvar='WANDB_MODEL', help="The model you want to download.")
@click.option("--kind", default="weights", type=click.Choice(['model', 'weights']))
@display_error
def download(model, kind):
    click.echo("Downloading model: {model}".format(
        model=click.style(model, bold=True)
    ))

    url = api.download_url(model, "%sUrl" % kind)
    length, response = api.download_file(url)
    with click.progressbar(length=length, label='Downloading %s' % kind,
                           fill_char=click.style('&', fg='green')) as bar:
        with open(url.split("/")[-1], "wb") as f:
            for data in response.iter_content(chunk_size=4096):
                f.write(data)
                bar.update(len(data))

if __name__ == "__main__":
    cli({})
