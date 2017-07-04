# -*- coding: utf-8 -*-

import click, sys
from wandb import Api, Error, Sync, Config, __version__
import random, time, os, re, netrc, logging, json, glob, io, stat
from functools import wraps
from click.utils import LazyFile
from click.exceptions import BadParameter, ClickException
import inquirer

logging.basicConfig(filename='/tmp/wandb.log', level=logging.INFO)

def normalize(host):
    return host.split("/")[-1].split(":")[0]

def logged_in(host, retry=True):
    """Check if our host is in .netrc"""
    try:
        conf = netrc.netrc()
        return conf.hosts[normalize(host)]
    except netrc.NetrcParseError as e:
        #chmod 0600 which is a common mistake, we could do this in `write_netrc`...
        os.chmod(os.path.expanduser('~/.netrc'), stat.S_IRUSR | stat.S_IWUSR)
        if retry:
            return logged_in(host, retry=False)
        else:
            click.secho("Unable to read ~/.netrc: "+e.message, fg="red")
            return None
    except IOError as e:
        click.secho("Unable to read ~/.netrc", fg="red")
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

def editor(marker='# Enter a description, markdown is allowed!\n'):
    message = click.edit('\n\n' + marker)
    if message is not None:
        return message.split(marker, 1)[0].rstrip('\n')
        
api = Api()
#TODO: Is this the best way to do this?
CONTEXT=dict(default_map=api.config())

class BucketGroup(click.Group):
    @display_error
    def get_command(self, ctx, cmd_name):
        rv = click.Group.get_command(self, ctx, cmd_name)
        if rv is not None:
            return rv

        try:
            project, bucket = api.parse_slug(cmd_name)
        except Error:
            return None
        #TODO: This is hacky as hell
        description = None
        if '-m' in sys.argv:
            description = sys.argv[sys.argv.index('-m') + 1]
        elif '--description' in sys.argv:
            description = sys.argv[sys.argv.index('--description') + 1]
        sync = Sync(api, project=project, bucket=bucket, description=description)
        if sync.source_proc:
            files = sys.argv[2:]
            sync.watch(files)
            return click.Command("sync", context_settings={'allow_extra_args': True})
        else:
            return None

@click.command(cls=BucketGroup)
@click.version_option(version=__version__)
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
def projects(entity, display=True):
    projects = api.list_projects(entity=entity)
    if len(projects) == 0:
        message = "No projects found for %s" % entity
    else:
        message = 'Latest projects for "%s"' % entity
    if display:
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
@click.option("--config/--no-config", help="Show the current configuration", default=False)
@click.option("--project", "-p", envvar='WANDB_PROJECT', help="The project you wish to upload to.")
@display_error
def status(bucket, config, project):
    if config:
        click.echo(click.style("Current Configuration", bold=True) + " (%s)" % api.config_file)
        config = api.config()
        click.echo(json.dumps(
            config,
            sort_keys=True,
            indent=2,
            separators=(',', ': ')
        ))
        click.echo(click.style("Logged in?", bold=True) + " %s\n" % bool(logged_in(config['base_url'])))
    project, bucket = api.parse_slug(bucket, project=project)
    parser = api.config_parser
    parser.read(".wandb/config")
    if parser.has_option("default", "files"):
        existing = set(parser.get("default", "files").split(","))
    else:
        existing = set()
    remote = api.download_urls(project, bucket)
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
    click.echo('File status for '+ click.style('"%s/%s" ' % (project, bucket), bold=True))
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
    parser.read(".wandb/config")
    if not parser.has_section("default"):
        raise ClickException("Directory not configured, run `wandb init` before adding files.")
    if parser.has_option("default", "files"):
        existing = parser.get("default", "files").split(",")
    else:
        existing = []
    stagedFiles = set(existing + [file.name for file in files])
    parser.set("default", "files", ",".join(stagedFiles))
    with open('.wandb/config', 'w') as configfile:
        parser.write(configfile)
    click.echo(click.style('Staged files for "%s": ' % project, bold=True) + ", ".join(stagedFiles))

@cli.command(context_settings=CONTEXT, help="Remove staged files")
@click.argument("files", nargs=-1)
@click.option("--project", "-p", prompt=True, envvar='WANDB_PROJECT', help="The project you wish to upload to.")
@display_error
def rm(files, project):
    parser = api.config_parser
    parser.read(".wandb/config")
    if parser.has_option("default", "files"):
        existing = parser.get("default", "files").split(",")
    else:
        existing = []
    for file in files:
        if file not in existing:
            raise ClickException("%s is not staged" % file)
        existing.remove(file)
    parser.set("default", "files", ",".join(existing))
    with open('.wandb/config', 'w') as configfile:
        parser.write(configfile)
    click.echo(click.style('Staged files for "%s": ' % project, bold=True) + ", ".join(existing))
    
@cli.command(context_settings=CONTEXT, help="Push files to Weights & Biases")
@click.argument("bucket", envvar='WANDB_BUCKET')
@click.option("--project", "-p", envvar='WANDB_PROJECT', help="The project you wish to upload to.")
@click.option("--description", "-m", help="A description to associate with this upload.")
@click.option("--entity", "-e", default="models", envvar='WANDB_ENTITY', help="The entity to scope the listing to.")
@click.option("--force/--no-force", "-f", default=False, help="Whether to force git tag creation.")
@click.argument("files", type=click.File('rb'), nargs=-1)
@click.pass_context
@display_error
def push(ctx, bucket, project, description, entity, force, files):
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

    api.tag_and_push(bucket, description, force)
    #TODO: Deal with files in a sub directory
    urls = api.upload_urls(project, files=[f.name for f in files], bucket=bucket, description=description, entity=entity)
    if api.latest_config:
        api.update_bucket(urls["bucket_id"], description=description, entity=entity, config=api.latest_config)

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

    urls = api.download_urls(project, bucket=bucket, entity=entity)
    if len(urls) == 0:
        raise ClickException("Bucket is empty")
    click.echo("Downloading: {project}/{bucket}".format(
        project=click.style(project, bold=True), bucket=bucket
    ))

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

@cli.command(context_settings=CONTEXT, help="Login to Weights & Biases")
@display_error
def login():
    #TODO: xdg-open dumps a bunch of output on Ubuntu if theirs no browser
    code = 1 #click.launch("https://app.wandb.ai/profile")
    if code != 0:
        click.echo("You can find your API keys here: https://app.wandb.ai/profile")
    key = click.prompt("{warning} Paste an API key from your profile".format(
            warning=click.style("Not authenticated!", fg="red")), default="")
    host = api.config()['base_url']
    if key:
        write_netrc(host, "user", key)

@cli.command(context_settings=CONTEXT, help="Configure a directory with Weights & Biases")
@click.pass_context
@display_error
def init(ctx):
    if(os.path.exists(".wandb")):
        click.confirm(click.style("This directory is already configured, should we overwrite it?", fg="red"), abort=True)
    click.echo(click.style("Let's setup this directory for W&B!", fg="green", bold=True))
    
    if logged_in(api.config('base_url')) is None:
        ctx.invoke(login)

    entity = click.prompt("What username or org should we use?", default=api.viewer().get('entity', 'models'))
    #TODO: handle the case of a missing entity
    result = ctx.invoke(projects, entity=entity, display=False)

    if len(result) == 0:
        project = click.prompt("Enter a name for your first project")
        description = editor()
        api.create_project(project, entity=entity, description=description)
    else:
        project_names = [project["name"] for project in result]
        question = inquirer.List('project', message="Which project should we use?", choices=project_names + ["Create New"])
        project = inquirer.prompt([question])['project']
        #TODO: check with the server if the project exists
        if project == "Create New":
            project = click.prompt("Enter a name for your new project")
            description = editor()
            api.create_project(project, entity=entity, description=description)

    ctx.invoke(config_init, False)

    with open(".wandb/config", "w") as file:
        file.write("[default]\nentity: {entity}\nproject: {project}".format(entity=entity, project=project))

    click.echo(click.style("This directory is configured!  Try these next:\n", fg="green")+ 
        """
* Run `{push}` to add your first file.
* Pipe your training output to push changed files and logs: `{sync}`.
* Track config params by adding `{flags}` to your training script.
* `{config}` to add or change configuration parameters.
* Pull popular models into your project with: `{pull}`.
    """.format(
        push=click.style("wandb push weights.h5", bold=True),
        flags=click.style("import wandb; conf = wandb.Config(FLAGS)", bold=True),
        sync=click.style("my_training.py | wandb bucket_name", bold=True),
        config=click.style("wandb config set batch_size=10", bold=True),
        pull=click.style("wandb pull models/inception-v4", bold=True)
    ))

@cli.group()
@click.pass_context
@display_error
def config(ctx):
    """Manage this projects configuration.

Examples: 

    wandb config set param=2 --description="Some tunning parameter"
    wandb config del param                                          
    wandb config show
    """
    pass

@config.command("init", help="Initialize a directory with wandb configuration")
@display_error
def config_init(prompt=True):
    config_path = os.getcwd()+"/.wandb"
    config = Config()
    if os.path.isdir(config_path):
        if prompt:
            click.confirm(click.style("This directory is already initialized, should we overwrite it?", fg="red"), abort=True)
    else:
        #TODO: Temp to deal with migration
        tmp_path = config_path.replace(".wandb", ".wandb.tmp")
        if os.path.isfile(config_path):
            os.rename(config_path, tmp_path)
        os.mkdir(config_path)
        if os.path.isfile(tmp_path):
            os.rename(tmp_path, tmp_path.replace(".wandb.tmp", ".wandb/config"))
    config.batch_size_desc = "Number of training examples in a mini-batch"
    config.batch_size = 32
    config.persist()
    if prompt:
        click.echo("""Configuration initialized, use `wandb config set` to set parameters.  Then in your training script:

import wandb
conf = wandb.Config()
conf.batch_size
""")

@config.command(help="Show the current config")
@click.option("--format", help="The format to dump the config as", default="python", type=click.Choice(['python', 'yaml', 'json']))
@display_error
def show(format, changed=[], diff=False):
    if len(changed) == 0 and diff:
        click.secho("No parameters were changed", fg="red")
    elif diff:
        click.echo("%i parameters changed: " % len(changed))
    config = Config()
    if len(vars(config)) == 0:
        click.secho("No configuration found in this directory, run `wandb config init`", fg="red")
    if format == "yaml":
        click.echo("%s" % config)
    elif format == "json":
        click.echo(json.dumps(vars(config)))
    elif format == "python":
        res = ""
        for key in set(config.keys + changed):
            if config.desc(key):
                res += "# %s\n" % config.desc(key)
            style = None
            if key in changed:
                style = "green" if config.get(key) else "red"
            res += click.style("%s=%r\n" % (key, config.get(key)), bold=True if style is None else False, fg=style)
        click.echo(res)

@config.command("import", help="Import configuration parameters")
@click.option("--format", "-f", help="The format to parse the imported params", default="python", type=click.Choice(["python"]))
@click.pass_context
@display_error
def import_config(ctx, format):
    data = editor("# Paste python comments and variable definitions above")
    desc = None
    config = Config()
    imported = []
    if data:
        for line in data.split("\n"):
            if line.strip().startswith("#"):
                desc = line.strip(" #")
            elif "=" in line:
                try:
                    key, value = [str(part.strip()) for part in line.split("=")]
                    if len(value) == 0:
                        continue
                    config[key] = value
                    imported.append(key)
                    if desc:
                        config[key+"_desc"] = desc
                    desc = None
                except ValueError:
                    logging.error("Invalid line: %s" % line)
            else:
                logging.warn("Skipping line %s", line)
        config.persist()
    ctx.invoke(show, changed=imported, diff=True)

@config.command("set", help="Set config variables with key=value pairs")
@click.argument("key_values", nargs=-1)
@click.option("--description", "-d", help="A description for the config value if specifying one pair")
@click.pass_context
@display_error
def config_set(ctx, key_values, description=None):
    config = Config()
    if len(key_values) == 0:
        raise ClickException("Must specify at least 1 key value pair i.e. `wandb config set epochs=11`")
    if len(key_values) > 1 and description:
        raise ClickException("Description can only be specified with 1 key value pair.")
    changed = []
    for pair in key_values:
        try:
            key, value = pair.split("=")
        except ValueError:
            key = pair
            value = None
        if value:
            changed.append(key)
            config[str(key)] = value
        if description:
            config[str(key)+"_desc"] = description
    config.persist()
    ctx.invoke(show, changed=changed, diff=True)

@config.command("del", help="Delete config variables")
@click.argument("keys", nargs=-1)
@click.pass_context
@display_error
def delete(ctx, keys):
    config = Config()
    if len(keys) == 0:
        raise ClickException("Must specify at least 1 key i.e. `wandb config rm epochs`")
    changed = []
    for key in keys:
        del config[str(key)]
        changed.append(key)
    config.persist()
    ctx.invoke(show, changed=changed, diff=True)

if __name__ == "__main__":
    cli()
