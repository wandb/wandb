# -*- coding: utf-8 -*-

import click
from wandb import Api, Error
import random, time, os, re, netrc, logging, json, glob, io
from functools import wraps
from click.utils import LazyFile
from click.exceptions import BadParameter, ClickException
import inquirer

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
    """Console script for Weights & Biases"""
    pass

@cli.command(context_settings=CONTEXT, help="List models")
@click.option("--entity", "-e", default="models", envvar='WANDB_ENTITY', help="The entity to scope the listing to.")
@display_error
def models(entity):
    models = api.list_models(entity=entity)
    if len(models) == 0:
        message = "No models found for %s" % entity
    else:
        message = 'Latest models for "%s"' % entity
    click.echo(click.style(message, bold=True))
    for model in models:
        click.echo("".join(
            (click.style(model['name'], fg="blue", bold=True), 
            " - ", 
            str(model['description']).split("\n")[0])
        ))
    return models

@cli.command(context_settings=CONTEXT, help="List buckets in a model")
@click.argument("model", envvar='WANDB_MODEL')
@click.option("--model", "-M", prompt=True, envvar='WANDB_MODEL', help="The model you wish to upload to.")
@click.option("--entity", "-e", default="models", envvar='WANDB_ENTITY', help="The entity to scope the listing to.")
@display_error
def buckets(model, entity):
    click.echo(click.style('Latest buckets for model "%s"' % model, bold=True))
    buckets = api.list_buckets(model, entity=entity)
    for bucket in buckets:
        click.echo("".join(
            (click.style(bucket['name'], fg="blue", bold=True), 
            " - ", 
            (bucket['description'] or "").split("\n")[0])
        ))

@cli.command(context_settings=CONTEXT, help="List staged files & remote files")
@click.argument("bucket", envvar='WANDB_BUCKET')
@click.option("--model", "-M", prompt=True, envvar='WANDB_MODEL', help="The model you wish to upload to.")
@display_error
def status(bucket, model):
    parts = bucket.split("/")
    if len(parts) == 2:
        model = parts[0]
        bucket = parts[1]
    parser = api.config_parser
    parser.read(".wandb")
    if parser.has_option("default", "files"):
        existing = parser.get("default", "files").split(",")
    else:
        existing = []
    click.echo(click.style('Staged files for "%s": ' % model, bold=True) + ", ".join(existing))
    remote = api.download_urls(model)
    click.echo(click.style('Remote files for "%s/%s": ' % (model, bucket), bold=True) + ", ".join([name for name in remote]))


@cli.command(context_settings=CONTEXT, help="Add staged files")
@click.argument("files", type=click.File('rb'), nargs=-1)
@click.option("--model", "-M", prompt=True, envvar='WANDB_MODEL', help="The model you wish to upload to.")
@display_error
def add(files, model):
    parser = api.config_parser
    parser.read(".wandb")
    if not parser.has_section("default"):
        raise ClickException("Directory not configured, run `wandb init` before adding files.")
    if parser.has_option("default", "files"):
        existing = parser.get("default", "files").split(",")
    else:
        existing = []
    stagedFiles = set(existing + [file.name for file in files])
    parser.set("default", "files", ",".join(stagedFiles))
    with open('.wandb', 'w') as configfile:
        parser.write(configfile)
    click.echo(click.style('Staged files for "%s": ' % model, bold=True) + ", ".join(stagedFiles))

@cli.command(context_settings=CONTEXT, help="Remove staged files")
@click.argument("files", nargs=-1)
@click.option("--model", "-M", prompt=True, envvar='WANDB_MODEL', help="The model you wish to upload to.")
@display_error
def rm(files, model):
    parser = api.config_parser
    parser.read(".wandb")
    if parser.has_option("default", "files"):
        existing = parser.get("default", "files").split(",")
    else:
        existing = []
    for file in files:
        if file not in existing:
            raise ClickException("%s is not staged" % file)
        existing.remove(file)
    parser.set("default", "files", ",".join(existing))
    with open('.wandb', 'w') as configfile:
        parser.write(configfile)
    click.echo(click.style('Staged files for "%s": ' % model, bold=True) + ", ".join(existing))
    
@cli.command(context_settings=CONTEXT, help="Push files to Weights & Biases")
@click.argument("bucket", envvar='WANDB_BUCKET')
@click.option("--model", "-M", prompt=True, envvar='WANDB_MODEL', help="The model you wish to upload to.")
@click.option("--description", "-m", help="A description to associate with this upload.")
@click.argument("files", type=click.File('rb'), nargs=-1)
@click.pass_context
@display_error
def push(ctx, bucket, model, description, files):
    #TODO: do we support the case of a bucket with the same name as a file?
    if os.path.exists(bucket):
        raise BadParameter("Bucket is required if files are specified.")
    parts = bucket.split("/")
    if len(parts) == 2:
        model = parts[0]
        bucket = parts[1]

    click.echo("Uploading model: {model}/{bucket}".format(
        model=click.style(model, bold=True), bucket=bucket))
    if description is None:
        description = editor()
    
    candidates = []
    if len(files) == 0:
        if api.config().get("files"):
            fileNames = api.config()['files'].split(",")
            files = [LazyFile(fileName, 'rb') for fileName in fileNames]
        else:
            patterns = ("*.h5", "*.hdf5", "*.json", "*.meta", "*checkpoint*")
            for pattern in patterns:
                candidates.extend(glob.glob(pattern))          
            if len(candidates) == 0:
                raise BadParameter("Couldn't auto-detect files, specify manually or use `wandb.add`", param_hint="FILES")

            choices = inquirer.prompt([inquirer.Checkbox('files', message="Which files do you want to push? (left and right arrows to select)", 
                choices=[c for c in candidates])])
            files = [LazyFile(choice, 'rb') for choice in choices['files']]

    if len(files) > 5:
        raise BadParameter("A maximum of 5 files can be in a single bucket.", param_hint="FILES")

    #TODO: Deal with files in a sub directory
    urls = api.upload_urls(model, files=[f.name for f in files], bucket=bucket, description=description)

    for file in files:
        length = os.fstat(file.fileno()).st_size
        with click.progressbar(length=length, label='Uploading file: %s' % (file.name),
            fill_char=click.style('&', fg='green')) as bar:
            print(urls)
            api.upload_file( urls[file.name]['url'], file, lambda bites: bar.update(bites) )

@cli.command(context_settings=CONTEXT, help="Pull files from Weights & Biases")
@click.argument("bucket", envvar='WANDB_BUCKET')
@click.option("--model", "-M", prompt=True, envvar='WANDB_MODEL', help="The model you want to download.")
@click.option("--kind", "-k", default="all", type=click.Choice(['all', 'model', 'weights', 'other']))
@display_error
def pull(model, bucket, kind):
    parts = bucket.split("/")
    if len(parts) == 2:
        model = parts[0]
        bucket = parts[1]
        
    click.echo("Downloading model: {model}/{bucket}".format(
        model=click.style(model, bold=True), bucket=bucket
    ))

    urls = api.download_urls(model, bucket=bucket)
    for name in urls:
        length, response = api.download_file(urls[name]['url'])
        with click.progressbar(length=length, label='Downloading %s' % name,
                            fill_char=click.style('&', fg='green')) as bar:
            with open(name, "wb") as f:
                for data in response.iter_content(chunk_size=4096):
                    f.write(data)
                    bar.update(len(data))

@cli.command(help="Show this directories configuration")
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

@cli.command(context_settings=CONTEXT, help="Configure a directory with Weights & Biases")
@click.pass_context
@display_error
def init(ctx):
    if(os.path.isfile(".wandb")):
        click.confirm(click.style("This directory is already configured, should we overwrite it?", fg="red"), abort=True)
    click.echo(click.style("Let's setup this directory for W&B!", fg="green", bold=True))
    host = api.config()['base_url']
    if loggedIn(host) is None:
        key = click.prompt("{warning} Enter an api key from https://app.wandb.ai/profile to enable uploads".format(
            warning=click.style("Not authenticated!", fg="red")), default="")
        #TODO: get the default entity from the API
        if key:
            login(host, "user", key)

    entity = click.prompt("What entity should we scope to?", default="models")
    #TODO: handle the case of a missing entity
    result = ctx.invoke(models, entity=entity)

    if len(result) == 0:
        model = click.prompt("Enter a name for your first model.")
        description = editor()
        api.create_model(model, entity=entity, description=description)
    else:
        model_names = [model["name"] for model in result]
        question = inquirer.List('model', message="Which model should we use?", choices=model_names + ["Create New"])
        model = inquirer.prompt([question])['model']
        #TODO: check with the server if the model exists
        if model == "Create New":
            model = click.prompt("Enter a name for your new model.")
            description = editor()
            api.create_model(model, entity=entity, description=description)

    with open(".wandb", "w") as file:
        file.write("[default]\nentity: {entity}\nmodel: {model}".format(entity=entity, model=model))
    click.echo(click.style("This directory is configured, run `wandb push` to sync your first model!", fg="green"))

if __name__ == "__main__":
    cli()
