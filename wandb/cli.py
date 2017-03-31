# -*- coding: utf-8 -*-

import click
from wandb import Api, Error
import random, time, os, re, netrc, logging, json, glob, io
from functools import wraps
from click.utils import LazyFile
from click.exceptions import BadParameter, ClickException

logging.basicConfig(filename='/tmp/wandb.log', level=logging.INFO)

def normalize(host):
    return host.split("/")[-1].split(":")[0]

def loggedIn(host):
    """Check if our host is in .netrc"""
    try:
        conf = netrc.netrc()
        return conf.hosts[normalize(host)]
    except:
        return None

def login(host, entity, key):
    """Add our host and key to .netrc"""
    print("Appending to netrc %s" %os.path.expanduser('~/.netrc')) 
    with open(os.path.expanduser('~/.netrc'), 'a') as f:
        f.write("""machine {host}
    login {entity}
    password {key}
""".format(host=normalize(host), entity=entity, key=key))

def display_error(func):
    """Function decorator for catching common errors and re-raising as wandb.Error"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Error as e:
            raise ClickException(e)
            
    return wrapper

def editor():
    MARKER = '# Enter a description of this revision, markdown is allowed!\n'
    message = click.edit('\n\n' + MARKER)
    if message is not None:
        return message.split(MARKER, 1)[0].rstrip('\n')

api = Api()
#TODO: Is this the best way to do this?
CONTEXT=dict(default_map=api.config())

@click.group()
def cli():
    """Console script for wandb"""
    pass

@cli.command(context_settings=CONTEXT)
@click.option("--entity", "-e", default="models", envvar='WANDB_ENTITY', help="The entity to scope the listing to.")
@display_error
def models(entity):
    click.echo(click.style('Latest models for entity "%s"' % entity, bold=True))
    models = api.list_models(entity=entity)
    if len(models) == 0:
        raise ClickException("No models found for %s, add models at: https://app.wandb.ai/models/new" % entity)
    for model in models:
        click.echo("".join(
            (click.style(model['name'], fg="blue", bold=True), 
            " - ", 
            model['description'].split("\n")[0])
        ))

@cli.command(context_settings=CONTEXT)
@click.option("--model", "-M", prompt=True, envvar='WANDB_MODEL', help="The model you wish to upload to.")
@click.option("--entity", "-e", default="models", envvar='WANDB_ENTITY', help="The entity to scope the listing to.")
@display_error
def tags(model, entity):
    click.echo(click.style('Latest tags for model "%s"' % model, bold=True))
    tags = api.list_tags(model, entity=entity)
    for tag in tags:
        click.echo("".join(
            (click.style(tag['name'], fg="blue", bold=True), 
            " - ", 
            (tag['description'] or "").split("\n")[0])
        ))

@cli.command(context_settings=CONTEXT)
@click.option("--model", "-M", prompt=True, envvar='WANDB_MODEL', help="The model you wish to upload to.")
@click.option("--tag", "-t", envvar='WANDB_TAG', help="An optional tag to work with.")
@click.option("--description", "-d", "-m", help="A description to associate with this upload.")
@click.argument("files", type=click.File('rb'), nargs=-1)
@click.pass_context
@display_error
def upload(ctx, model, tag, description, files):
    click.echo("Uploading model: {model}".format(
        model=click.style(model, bold=True)))
    if description is None:
        description = editor()
    urls = api.upload_urls(model, tag=tag, description=description)
    valid_exts = ["*.%s" % ext for ext in urls]
    if len(files) == 0:
        files = []
        for ext in urls:
            candidates = glob.glob("*.%s" % ext)
            if len(candidates) > 0:
                files.append(LazyFile(candidates[0], 'rb'))

    if len(files) == 0:
        raise BadParameter("Couldn't auto-detect locations, looked for %s" % 
            valid_exts, param_hint="FILES")

    if len(files) > 2:
        raise BadParameter("Only a weights file and a model file can be uploaded.", param_hint="FILES")

    for file in files:
        ext = file.name.split(".")[-1]
        if urls.get(ext):
            length = os.fstat(file.fileno()).st_size
            with click.progressbar(length=length, label='Uploading %s file: %s' % (urls[ext][0], file.name),
                                fill_char=click.style('&', fg='green')) as bar:
                api.upload_file( urls[ext][1], file, lambda bites: bar.update(bites) )
        else:
            raise BadParameter("'%s' has an invalid extension. Valid extensions: %s" % 
                (file.name, valid_exts), param_hint="FILES")

@cli.command()
def config():
    click.echo(click.style("Current Configuration", bold=True))
    config = api.config()
    click.echo("From file: %s" % api.config_file)
    click.echo("Logged in? %s" % bool(loggedIn(config['base_url'])))
    click.echo(json.dumps(
        config,
        sort_keys=True,
        indent=2,
        separators=(',', ': ')
    ))

@cli.command(context_settings=CONTEXT, help="Configure a directory for use with Weights & Biases")
@click.pass_context
@display_error
def init(ctx):
    if(os.path.isfile(".wandb")):
        click.confirm(click.style("This directory is already configured, should we overwrite it?", fg="red"), abort=True)
    click.echo(click.style("Let's setup this directory for W&B!", fg="green", bold=True))
    entity = click.prompt("What entity should we scope to?", default="models")
    host = api.config()['base_url']
    if loggedIn(host) is None:
        key = click.prompt("{warning} Enter an api key from https://app.wandb.ai/profile to enable uploads".format(
            warning=click.style("Not authenticated!", fg="red")), default="")
        if key:
            login(host, entity, key)
    ctx.invoke(models, entity=entity)
    model = click.prompt("Enter a model name from above")
    with open(".wandb", "w") as file:
        file.write("[default]\nentity: {entity}\nmodel: {model}".format(entity=entity, model=model))
    click.echo(click.style("This directory is configured, run `wandb upload` to upload your first model!", fg="green"))

@cli.command(context_settings=CONTEXT)
@click.option("--model", "-M", prompt=True, envvar='WANDB_MODEL', help="The model you want to download.")
@click.option("--tag", "-t", default="default", envvar='WANDB_TAG', help="The model you want to download.")
@click.option("--kind", "-k", default="all", type=click.Choice(['all', 'model', 'weights']))
@display_error
def download(model, tag, kind):
    click.echo("Downloading model: {model}".format(
        model=click.style(model, bold=True)
    ))

    urls = api.download_urls(model, tag=tag)
    kinds = ['model', 'weights'] if kind == 'all' else [kind]
    for kind in [kind for kind in kinds if urls[kind]]:
        length, response = api.download_file(urls[kind])
        with click.progressbar(length=length, label='Downloading %s' % kind,
                            fill_char=click.style('&', fg='green')) as bar:
            with open(urls[kind].split("/")[-1], "wb") as f:
                for data in response.iter_content(chunk_size=4096):
                    f.write(data)
                    bar.update(len(data))

if __name__ == "__main__":
    cli()
