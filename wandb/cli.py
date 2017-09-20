# -*- coding: utf-8 -*-
import click, sys
import copy
import random, time, os, re, netrc, logging, json, glob, io, stat, subprocess
from functools import wraps
from click.utils import LazyFile
from click.exceptions import BadParameter, ClickException
import inquirer
import sys, traceback

from wandb import _set_cli_mode
_set_cli_mode()

from wandb import util
from wandb import Api, Error, Config, __version__, __stage_dir__
from wandb import wandb_run

logger = logging.getLogger(__name__)

def write_netrc(host, entity, key):
    """Add our host and key to .netrc"""
    try:
        normalized_host = host.split("/")[-1].split(":")[0]
        print("Appending to netrc %s" % os.path.expanduser('~/.netrc'))
        with open(os.path.expanduser('~/.netrc'), 'a') as f:
            f.write("""machine {host}
        login {entity}
        password {key}
    """.format(host=normalized_host, entity=entity, key=key))
        os.chmod(os.path.expanduser('~/.netrc'), stat.S_IRUSR | stat.S_IWUSR)
    except IOError as e:
        click.secho("Unable to read ~/.netrc", fg="red")
        return None

def display_error(func):
    """Function decorator for catching common errors and re-raising as wandb.Error"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Error as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
            logger.error('\n'.join(lines))
            raise ClickException(e)

    return wrapper

def editor(content='', marker='# Enter a description, markdown is allowed!\n'):
    message = click.edit(content + '\n\n' + marker)
    if message is not None:
        return message.split(marker, 1)[0].rstrip('\n')

api = Api()

# Some commands take project/entity etc. as arguments. We provide default
# values for those arguments from the current project configuration, as
# returned by api.settings()
CONTEXT=dict(default_map=api.settings())

class RunGroup(click.Group):
    @display_error
    def get_command(self, ctx, cmd_name):
        #TODO: check if cmd_name is a file in the current dir and not require `run`?
        rv = click.Group.get_command(self, ctx, cmd_name)
        if rv is not None:
            return rv

        return None

@click.command(cls=RunGroup)
@click.version_option(version=__version__)
@click.pass_context
def cli(ctx):
    """Weights & Biases

If the first argument is a file in the current directory run it.

   wandb train.py --arg=1
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

@cli.command(context_settings=CONTEXT, help="List runs in a project")
@click.option("--project", "-p", prompt=True, envvar='WANDB_PROJECT', help="The project you wish to list runs from.")
@click.option("--entity", "-e", default="models", envvar='WANDB_ENTITY', help="The entity to scope the listing to.")
@display_error
def runs(project, entity):
    click.echo(click.style('Latest runs for project "%s"' % project, bold=True))
    runs = api.list_runs(project, entity=entity)
    for run in runs:
        click.echo("".join(
            (click.style(run['name'], fg="blue", bold=True),
            " - ",
            (run['description'] or "").split("\n")[0])
        ))

@cli.command(context_settings=CONTEXT, help="List local & remote file status")
@click.argument("run", envvar='WANDB_RUN')
@click.option("--settings/--no-settings", help="Show the current settings", default=False)
@click.option("--project", "-p", envvar='WANDB_PROJECT', help="The project you wish to upload to.")
@display_error
def status(run, settings, project):
    if settings:
        click.echo(click.style("Current Settings", bold=True) + " (%s)" % api.settings_file)
        settings = api.settings()
        click.echo(json.dumps(
            settings,
            sort_keys=True,
            indent=2,
            separators=(',', ': ')
        ))
        click.echo(click.style("Logged in?", bold=True) + " %s\n" % bool(api.api_key))
    project, run = api.parse_slug(run, project=project)
    existing = set() #TODO: populate this set with the current files in the run dir
    remote = api.download_urls(project, run)
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
    click.echo('File status for '+ click.style('"%s/%s" ' % (project, run), bold=True))
    if len(not_synced) > 0:
        click.echo(click.style('Push needed: ', bold=True) + click.style(", ".join(not_synced), fg="red"))
    if len(only_remote) > 0:
        click.echo(click.style('Pull needed: ', bold=True) + click.style(", ".join(only_remote), fg="red"))
    if len(up_to_date) > 0:
        click.echo(click.style('Up to date: ', bold=True) + click.style(", ".join(up_to_date), fg="green"))

@cli.command(context_settings=CONTEXT, help="Store notes for a future training run")
@display_error
def describe():
    path = __stage_dir__+'description.md'
    existing = (os.path.exists(path) and open(path).read()) or ''
    description = editor(existing)
    if description:
        with open(path, 'w') as file:
            file.write(description)
    click.echo("Notes stored for next training run\nCalling wandb.sync() in your training script will persist them.")

@cli.command(context_settings=CONTEXT, help="Restore code and config state for a run")
@click.argument("run", envvar='WANDB_RUN')
@click.option("--branch/--no-branch", default=True, help="Whether to create a branch or checkout detached")
@click.option("--project", "-p", envvar='WANDB_PROJECT', help="The project you wish to upload to.")
@click.option("--entity", "-e", default="models", envvar='WANDB_ENTITY', help="The entity to scope the listing to.")
@display_error
def restore(run, branch, project, entity):
    project, run = api.parse_slug(run, project=project)
    commit, json_config, patch = api.run_config(project, run=run, entity=entity)
    if commit:
        branch_name = "wandb/%s" % run
        if branch and branch_name not in api.git.repo.branches:
            api.git.repo.git.checkout(commit, b=branch_name)
            click.echo("Created branch %s" % click.style(branch_name, bold=True))
        elif branch:
            click.secho("Using existing branch, run `git branch -D %s` from master for a clean checkout" % branch_name, fg="red")
            api.git.repo.git.checkout(branch_name)
        else:
            click.secho("Checking out %s in detached mode" % commit)
            api.git.repo.git.checkout(commit)

    if patch:
        with open(__stage_dir__+"diff.patch", "w") as f:
            f.write(patch)
        api.git.repo.git.execute(['git', 'apply', __stage_dir__+'diff.patch'])
        click.echo("Applied patch")

    config = Config()
    config.load_json(json_config)
    config.persist()
    click.echo("Restored config variables")

@cli.command(context_settings=CONTEXT, help="Push files to Weights & Biases")
@click.argument("run", envvar='WANDB_RUN')
@click.option("--project", "-p", envvar='WANDB_PROJECT', help="The project you wish to upload to.")
@click.option("--description", "-m", help="A description to associate with this upload.")
@click.option("--entity", "-e", default="models", envvar='WANDB_ENTITY', help="The entity to scope the listing to.")
@click.option("--force/--no-force", "-f", default=False, help="Whether to force git tag creation.")
@click.argument("files", type=click.File('rb'), nargs=-1)
@click.pass_context
@display_error
def push(ctx, run, project, description, entity, force, files):
    #TODO: do we support the case of a run with the same name as a file?
    if os.path.exists(run):
        raise BadParameter("Run id is required if files are specified.")
    project, run = api.parse_slug(run, project=project)

    click.echo("Updating run: {project}/{run}".format(
        project=click.style(project, bold=True), run=run))

    candidates = []
    if len(files) == 0:
        #TODO: do we want to do this?
        patterns = ("*.h5", "*.hdf5", "*.json", "*.meta", "*checkpoint*")
        for pattern in patterns:
            candidates.extend(glob.glob(pattern))
        if len(candidates) == 0:
            raise BadParameter("Couldn't auto-detect files, specify manually or use `wandb.add`", param_hint="FILES")

        choices = inquirer.prompt([inquirer.Checkbox('files', message="Which files do you want to push? (left and right arrows to select)",
            choices=[c for c in candidates])])
        files = [LazyFile(choice, 'rb') for choice in choices['files']]

    #TODO: Deal with files in a sub directory
    api.push(project, files=[f.name for f in files], run=run,
        description=description, entity=entity, force=force, progress=sys.stdout)

@cli.command(context_settings=CONTEXT, help="Pull files from Weights & Biases")
@click.argument("run", envvar='WANDB_RUN')
@click.option("--project", "-p", envvar='WANDB_PROJECT', help="The project you want to download.")
@click.option("--kind", "-k", default="all", type=click.Choice(['all', 'model', 'weights', 'other']))
@click.option("--entity", "-e", default="models", envvar='WANDB_ENTITY', help="The entity to scope the listing to.")
@display_error
def pull(project, run, kind, entity):
    project, run = api.parse_slug(run, project=project)

    urls = api.download_urls(project, run=run, entity=entity)
    if len(urls) == 0:
        raise ClickException("Run has no files")
    click.echo("Downloading: {project}/{run}".format(
        project=click.style(project, bold=True), run=run
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
    # Import in here for performance reasons
    import webbrowser
    #TODO: use Oauth and a local webserver: https://community.auth0.com/questions/6501/authenticating-an-installed-cli-with-oidc-and-a-th
    url = "https://app.wandb.ai/profile"
    #TODO: google cloud SDK check_browser.py
    launched = webbrowser.open_new_tab(url)
    if launched:
        click.echo('Opening [{0}] in a new tab in your default browser.'.format(url))
    else:
        click.echo("You can find your API keys here: {0}".format(url))

    key = click.prompt("{warning} Paste an API key from your profile".format(
            warning=click.style("Not authenticated!", fg="red")),
            value_proc=lambda x: x.strip())

    host = api.settings()['base_url']
    if key:
        #TODO: get the username here...
        #username = api.viewer().get('entity', 'models')
        write_netrc(host, "user", key)

@cli.command(context_settings=CONTEXT, help="Configure a directory with Weights & Biases")
@click.pass_context
@display_error
def init(ctx):
    # TODO: This is commented out because we always automatically create this dir in __init__.py
    # however this isn't ideal, we'll litter the filesystem with wandb directories.
    #if(os.path.exists(__stage_dir__)):
    #    click.confirm(click.style("This directory is already configured, should we overwrite it?", fg="red"), abort=True)
    click.echo(click.style("Let's setup this directory for W&B!", fg="green", bold=True))
    global api

    if api.api_key is None:
        ctx.invoke(login)
        api = Api()

    entity = click.prompt("What username or org should we use?", default=api.viewer().get('entity', 'models'))
    #TODO: handle the case of a missing entity
    result = ctx.invoke(projects, entity=entity, display=False)

    if len(result) == 0:
        project = click.prompt("Enter a name for your first project")
        description = editor()
        api.upsert_project(project, entity=entity, description=description)
    else:
        project_names = [project["name"] for project in result]
        question = inquirer.List('project', message="Which project should we use?", choices=project_names + ["Create New"])
        project = inquirer.prompt([question])['project']
        #TODO: check with the server if the project exists
        if project == "Create New":
            project = click.prompt("Enter a name for your new project")
            description = editor()
            api.upsert_project(project, entity=entity, description=description)
        else:
            ids = [res['id'] for res in result if res['name'] == project]
            if len(ids) > 0:
                api.upsert_project(project, id=ids[0], entity=entity)

    ctx.invoke(config_init, False)

    with open(os.path.join(__stage_dir__, 'settings'), "w") as file:
        file.write("[default]\nentity: {entity}\nproject: {project}\n".format(entity=entity, project=project))

    with open(os.path.join(__stage_dir__, '.gitignore'), "w") as file:
        file.write("*\n!settings")

    click.echo(click.style("This directory is configured!  Try these next:\n", fg="green")+
        """
* Track runs by calling sync in your training script `{flags}`.
* Run `{push}` to manually add a file.
* `{config}` to add or change configuration defaults.
* Pull popular models into your project with: `{pull}`.
    """.format(
        push=click.style("wandb push run_id weights.h5", bold=True),
        flags=click.style("import wandb; run = wandb.sync(config=tf.__FLAGS__)", bold=True),
        config=click.style("wandb config set batch_size=10", bold=True),
        pull=click.style("wandb pull models/inception-v4", bold=True)
    ))

RUN_CONTEXT = copy.copy(CONTEXT)
RUN_CONTEXT['allow_extra_args'] = True
RUN_CONTEXT['ignore_unknown_options'] = True
@cli.command(context_settings=RUN_CONTEXT, help="Launch a job")
@click.pass_context
@click.argument('program')
@click.argument('args', nargs=-1)
@click.option('--id', default=None,
        help='Run id to use, default is to generate.')
@click.option('--dir', default=None,
        help='Files in this directory will be saved to wandb, defaults to wandb/run-<run_id>')
@click.option('--glob', default='*', multiple=True,
        help='New files in <run_dir> that match will be saved to wandb. (default: \'*\')')
@display_error
def run(ctx, program, args, id, dir, glob):
    env = copy.copy(os.environ)
    env['WANDB_MODE'] = 'run'
    if id is None:
        id = wandb_run.generate_id()
    env['WANDB_RUN_ID'] = id
    if dir is None:
        dir = wandb_run.run_dir_path(id, dry=False)
        util.mkdir_exists_ok(dir)
    env['WANDB_RUN_DIR'] = dir
    proc = util.SafeSubprocess([program] + list(args), env=env, read_output=False)
    proc.run()
    while True:
        time.sleep(0.1)
        exitcode = proc.poll()
        if exitcode is not None:
            print('wandb: job (%s) Process exited with code: %s' % (program, exitcode))
            break

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
    config_path = os.path.join(os.getcwd(), __stage_dir__)
    config = Config()
    if os.path.isdir(config_path):
        if prompt:
            click.confirm(click.style("This directory is already initialized, should we overwrite it?", fg="red"), abort=True)
    else:
        os.mkdir(config_path)
    config.epochs_desc = "Number epochs to train over"
    config.epochs = 32
    config.persist()
    if prompt:
        click.echo("""Configuration initialized, use `wandb config set` to set parameters.  Then in your training script:

import wandb
conf = wandb.sync()
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
