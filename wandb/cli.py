# -*- coding: utf-8 -*-

import click, sys
from wandb import Api, Error, Sync
import random, time, os, re, netrc, logging, json, glob, io
from functools import wraps
from click.utils import LazyFile
from click.exceptions import BadParameter, ClickException
import inquirer

logging.basicConfig(filename='/tmp/wandb.log', level=logging.INFO)

def normalize(host):
    return host.split("/")[-1].split(":")[0]

def logged_in(host):
    """Check if our host is in .netrc"""
    try:
        conf = netrc.netrc()
        return conf.hosts[normalize(host)]
    except:
        return None

def write_netrc(host, entity, key):
    """Add our host and key to .netrc"""
    print("Appending to netrc %s" % os.path.expanduser('~/.netrc')) 
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

class BucketGroup(click.Group):
    def get_command(self, ctx, cmd_name):
        rv = click.Group.get_command(self, ctx, cmd_name)
        if rv is not None:
            return rv

        try:
            project, bucket = api.parse_slug(cmd_name)
        except Error:
            return None

        sync = Sync(api, project=project, bucket=bucket)
        if sync.source_proc:
            files = sys.argv[2:]
            sync.watch(files)
            return click.Command("sync", context_settings={'allow_extra_args': True})
        else:
            return None

@click.command(cls=BucketGroup)
@click.pass_context
def cli(ctx):
    """Weights & Biases

If no command is specified and input is piped, the source command and it's 
output will be saved to the bucket and the files uploaded when modified.

   ./train.sh arg1 arg2 | wandb imagenet/v2 model.json weights.h5
    """
    pass        

@cli.command(context_settings=CONTEXT, help="List projects")
@click.option("--entity", "-e", default="models", envvar='WANDB_ENTITY', help="The entity to scope the listing to.")
@display_error
def projects(entity):
    projects = api.list_projects(entity=entity)
    if len(projects) == 0:
        message = "No projects found for %s" % entity
    else:
        message = 'Latest projects for "%s"' % entity
    click.echo(click.style(message, bold=True))
    for project in projects:
        click.echo("".join(
            (click.style(project['name'], fg="blue", bold=True), 
            " - ", 
            str(project['description']).split("\n")[0])
        ))
    return projects

@cli.command(context_settings=CONTEXT, help="List buckets in a project")
@click.argument("project", envvar='WANDB_PROJECT')
@click.option("--project", "-p", prompt=True, envvar='WANDB_PROJECT', help="The project you wish to upload to.")
@click.option("--entity", "-e", default="models", envvar='WANDB_ENTITY', help="The entity to scope the listing to.")
@display_error
def buckets(project, entity):
    click.echo(click.style('Latest buckets for project "%s"' % project, bold=True))
    buckets = api.list_buckets(project, entity=entity)
    for bucket in buckets:
        click.echo("".join(
            (click.style(bucket['name'], fg="blue", bold=True), 
            " - ", 
            (bucket['description'] or "").split("\n")[0])
        ))

@cli.command(context_settings=CONTEXT, help="List staged & remote files")
@click.argument("bucket", envvar='WANDB_BUCKET')
@click.option("--project", "-p", envvar='WANDB_PROJECT', help="The project you wish to upload to.")
@display_error
def status(bucket, project):
    project, bucket = api.parse_slug(bucket, project=project)
    parser = api.config_parser
    parser.read(".wandb")
    if parser.has_option("default", "files"):
        existing = set(parser.get("default", "files").split(","))
    else:
        existing = set()
    remote = api.download_urls(project)
    not_synced = set()
    remote_names = set([name for name in remote])
    for file in existing:
        meta = remote.get(file)
        if meta and not api.file_current(file, meta['md5']):
            not_synced.add(file)
        elif not meta:
            not_synced.add(file)
    #TODO: remove items that exists and have the md5
    only_remote = remote_names.difference(existing)
    up_to_date = existing.difference(only_remote).difference(not_synced)
    click.echo(click.style('File status for "%s/%s" ' % (project, bucket), bold=True))
    if len(not_synced) > 0:
        click.echo(click.style('Push needed: ', bold=True) + click.style(", ".join(not_synced), fg="red"))
    if len(only_remote) > 0:
        click.echo(click.style('Pull needed: ', bold=True) + click.style(", ".join(only_remote), fg="red"))
    if len(up_to_date) > 0:
        click.echo(click.style('Up to date: ', bold=True) + click.style(", ".join(up_to_date), fg="green"))
    if len(existing) == 0:
        click.echo(click.style("No files configured, add files with `wandb add filename`", fg="red"))


@cli.command(context_settings=CONTEXT, help="Add staged files")
@click.argument("files", type=click.File('rb'), nargs=-1)
@click.option("--project", "-p", prompt=True, envvar='WANDB_PROJECT', help="The project you wish to upload to.")
@display_error
def add(files, project):
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
    click.echo(click.style('Staged files for "%s": ' % project, bold=True) + ", ".join(stagedFiles))

@cli.command(context_settings=CONTEXT, help="Remove staged files")
@click.argument("files", nargs=-1)
@click.option("--project", "-p", prompt=True, envvar='WANDB_PROJECT', help="The project you wish to upload to.")
@display_error
def rm(files, project):
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
    click.echo(click.style('Staged files for "%s": ' % project, bold=True) + ", ".join(existing))
    
@cli.command(context_settings=CONTEXT, help="Push files to Weights & Biases")
@click.argument("bucket", envvar='WANDB_BUCKET')
@click.option("--project", "-p", envvar='WANDB_PROJECT', help="The project you wish to upload to.")
@click.option("--description", "-m", help="A description to associate with this upload.")
@click.option("--entity", "-e", default="models", envvar='WANDB_ENTITY', help="The entity to scope the listing to.")
@click.argument("files", type=click.File('rb'), nargs=-1)
@click.pass_context
@display_error
def push(ctx, bucket, project, description, entity, files):
    #TODO: do we support the case of a bucket with the same name as a file?
    if os.path.exists(bucket):
        raise BadParameter("Bucket is required if files are specified.")
    project, bucket = api.parse_slug(bucket, project=project)

    click.echo("Uploading project: {project}/{bucket}".format(
        project=click.style(project, bold=True), bucket=bucket))
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
    urls = api.upload_urls(project, files=[f.name for f in files], bucket=bucket, description=description, entity=entity)

    for file in files:
        length = os.fstat(file.fileno()).st_size
        with click.progressbar(length=length, label='Uploading file: %s' % (file.name),
            fill_char=click.style('&', fg='green')) as bar:
            api.upload_file( urls[file.name]['url'], file, lambda bites: bar.update(bites) )

@cli.command(context_settings=CONTEXT, help="Pull files from Weights & Biases")
@click.argument("bucket", envvar='WANDB_BUCKET')
@click.option("--project", "-p", envvar='WANDB_PROJECT', help="The project you want to download.")
@click.option("--kind", "-k", default="all", type=click.Choice(['all', 'model', 'weights', 'other']))
@click.option("--entity", "-e", default="models", envvar='WANDB_ENTITY', help="The entity to scope the listing to.")
@display_error
def pull(project, bucket, kind, entity):
    project, bucket = api.parse_slug(bucket, project=project)

    click.echo("Downloading: {project}/{bucket}".format(
        project=click.style(project, bold=True), bucket=bucket
    ))

    urls = api.download_urls(project, bucket=bucket, entity=entity)
    for name in urls:
        if api.file_current(name, urls[name]['md5']):
            click.echo("File %s is up to date" % name)
        else:
            length, response = api.download_file(urls[name]['url'])
            with click.progressbar(length=length, label='File %s' % name,
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
    click.echo("Logged in? %s" % bool(logged_in(config['base_url'])))
    click.echo(json.dumps(
        config,
        sort_keys=True,
        indent=2,
        separators=(',', ': ')
    ))

@cli.command(context_settings=CONTEXT, help="Login to Weights & Biases")
@display_error
def login():
    key = click.prompt("{warning} Enter an api key from https://app.wandb.ai/profile to enable uploads".format(
            warning=click.style("Not authenticated!", fg="red")), default="")
    #TODO: get the default entity from the API
    host = api.config()['base_url']
    if key:
        write_netrc(host, "user", key)

@cli.command(context_settings=CONTEXT, help="Configure a directory with Weights & Biases")
@click.pass_context
@display_error
def init(ctx):
    if(os.path.isfile(".wandb")):
        click.confirm(click.style("This directory is already configured, should we overwrite it?", fg="red"), abort=True)
    click.echo(click.style("Let's setup this directory for W&B!", fg="green", bold=True))
    
    if logged_in(api.config('base_url')) is None:
        ctx.invoke(login)

    entity = click.prompt("What username or org should we use?", default="models")
    #TODO: handle the case of a missing entity
    result = ctx.invoke(projects, entity=entity)

    if len(result) == 0:
        project = click.prompt("Enter a name for your first project.")
        description = editor()
        api.create_project(project, entity=entity, description=description)
    else:
        project_names = [project["name"] for project in result]
        question = inquirer.List('project', message="Which project should we use?", choices=project_names + ["Create New"])
        project = inquirer.prompt([question])['project']
        #TODO: check with the server if the project exists
        if project == "Create New":
            project = click.prompt("Enter a name for your new project.")
            description = editor()
            api.create_project(project, entity=entity, description=description)

    with open(".wandb", "w") as file:
        file.write("[default]\nentity: {entity}\nproject: {project}".format(entity=entity, project=project))
    click.echo(click.style("This directory is configured, run `wandb push` to sync your first project!", fg="green"))

if __name__ == "__main__":
    cli()
