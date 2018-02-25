from gql import Client, gql
from gql.client import RetryError
from gql.transport.requests import RequestsHTTPTransport
import datetime
import os
import requests
import ast
from functools import wraps
import logging
import hashlib
import os
import json
import yaml
import re
import wandb
from wandb import __version__, __stage_dir__, Error
from wandb.git_repo import GitRepo
from wandb import retry
from wandb import util
from .config import Config
import base64
import binascii
import click
import collections
import itertools
import logging
import requests
from six import BytesIO
from six.moves import configparser
from six.moves import queue
import socket
import subprocess
import threading
import time
import sys

from six import b

logger = logging.getLogger(__name__)


class Progress(object):
    """A helper class for displaying progress"""

    def __init__(self, file, callback=None):
        self.file = file
        if callback is None:
            def callback(bites, total): return (bites, total)
        self.callback = callback
        self.bytes_read = 0
        self.len = os.fstat(file.fileno()).st_size

    def read(self, size=-1):
        """Read bytes and call the callback"""
        bites = self.file.read(size)
        self.bytes_read += len(bites)
        self.callback(len(bites), self.bytes_read)
        return bites


class CommError(Error):
    """Error communicating with W&B"""
    pass


class UsageError(Error):
    """API Usage Error"""
    pass


def normalize_exceptions(func):
    """Function decorator for catching common errors and re-raising as wandb.Error"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        message = "Whoa, you found a bug."
        try:
            return func(*args, **kwargs)
        except requests.HTTPError as err:
            raise CommError(err.response)
        except RetryError as err:
            if "response" in dir(err.last_exception) and err.last_exception.response is not None:
                try:
                    message = err.last_exception.response.json().get(
                        'errors', [{'message': message}])[0]['message']
                except ValueError:
                    message = err.last_exception.response.text
            else:
                message = err.last_exception
            raise CommError(message)
        except Exception as err:
            # gql raises server errors with dict's as strings...
            if len(err.args) > 0:
                payload = err.args[0]
            else:
                payload = err
            if str(payload).startswith("{"):
                message = ast.literal_eval(str(payload))["message"]
            else:
                message = str(err)
            if os.getenv("WANDB_DEBUG") == "true":
                raise
            else:
                raise CommError(message)
    return wrapper


class Api(object):
    """W&B Api wrapper

    Note:
        Settings are automatically overridden by looking for
        a `wandb/settings` file in the current working directory or it's parent
        directory.  If none can be found, we look in the current users home
        directory.

    Args:
        default_settings(:obj:`dict`, optional): If you aren't using a settings
        file or you wish to override the section to use in the settings file
        Override the settings here.
    """

    HTTP_TIMEOUT = 10

    def __init__(self, default_settings=None, load_settings=True, retry_timedelta=datetime.timedelta(1)):
        self.default_settings = {
            'section': "default",
            'entity': "models",
            'run': "latest",
            'git_remote': "origin",
            'git_tag': False,
            'base_url': "https://api.wandb.ai"
        }
        self.retry_timedelta = retry_timedelta
        self.default_settings.update(default_settings or {})
        self._settings = None
        self.retries = 3
        self._settings_parser = configparser.ConfigParser()
        self.tagged = False
        if load_settings:
            potential_settings_paths = [
                os.path.expanduser('~/.wandb/settings')
            ]
            if __stage_dir__ is not None:
                potential_settings_paths.append(
                    os.path.join(os.getcwd(), __stage_dir__, 'settings'))
            files = self._settings_parser.read(potential_settings_paths)
            self.settings_file = files[0] if len(files) > 0 else "Not found"
        else:
            self.settings_file = "Not found"
        self.git = GitRepo(remote=self.settings("git_remote"))
        client = Client(
            retries=1,
            transport=RequestsHTTPTransport(
                headers={'User-Agent': self.user_agent},
                use_json=True,
                timeout=self.HTTP_TIMEOUT,
                auth=("api", self.api_key),
                url='%s/graphql' % self.settings('base_url')
            )
        )
        # 1-day worth of retry
        self.gql = retry.Retry(client.execute, retry_timedelta=retry_timedelta,
                               retryable_exceptions=(RetryError, requests.HTTPError))
        self._current_run_id = None
        self._file_stream_api = None

    def save_patches(self, out_dir):
        """Save the current state of this repository to one or more patches.

        Makes one patch against HEAD and another one against the most recent
        commit that occurs in an upstream branch. This way we can be robust
        to history editing as long as the user never does "push -f" to break
        history on an upstream branch.

        Writes the first patch to <out_dir>/diff.patch and the second to
        <out_dir>/upstream_diff_<commit_id>.patch.

        Args:
            out_dir (str): Directory to write the patch files.
        """
        if not self.git.repo:
            return False

        try:
            root = self.git.root
            if self.git.dirty:
                patch_path = os.path.join(out_dir, 'diff.patch')
                if self.git.has_submodule_diff:
                    with open(patch_path, 'wb') as patch:
                        # we diff against HEAD to ensure we get changes in the index
                        subprocess.check_call(
                            ['git', 'diff', '--submodule=diff', 'HEAD'], stdout=patch, cwd=root)
                else:
                    with open(patch_path, 'wb') as patch:
                        subprocess.check_call(
                            ['git', 'diff', 'HEAD'], stdout=patch, cwd=root)

            upstream_commit = self.git.get_upstream_fork_point()
            if upstream_commit and upstream_commit != self.git.repo.head.commit:
                sha = upstream_commit.hexsha
                upstream_patch_path = os.path.join(
                    out_dir, 'upstream_diff_{}.patch'.format(sha))
                if self.git.has_submodule_diff:
                    with open(upstream_patch_path, 'wb') as upstream_patch:
                        subprocess.check_call(
                            ['git', 'diff', '--submodule=diff', sha], stdout=upstream_patch, cwd=root)
                else:
                    with open(upstream_patch_path, 'wb') as upstream_patch:
                        subprocess.check_call(
                            ['git', 'diff', sha], stdout=upstream_patch, cwd=root)
        except subprocess.CalledProcessError:
            logger.error('Error generating diff')

    def set_current_run_id(self, run_id):
        self._current_run_id = run_id

    def ensure_configured(self):
        # The WANDB_DEBUG check ensures tests still work.
        if not os.getenv('WANDB_DEBUG') and not self.settings("project"):
            wandb.termlog('wandb.init() called but system not configured.\n'
                          'Run "wandb init" or set environment variables to get started')
            sys.exit(1)

    @property
    def current_run_id(self):
        return self._current_run_id

    @property
    def user_agent(self):
        return 'W&B Client %s' % __version__

    @property
    def api_key(self):
        auth = requests.utils.get_netrc_auth(self.api_url)
        if auth:
            key = auth[-1]
        else:
            key = os.environ.get("WANDB_API_KEY")
        return key

    @property
    def api_url(self):
        return self.settings('base_url')

    @property
    def app_url(self):
        api_url = self.api_url
        if api_url.endswith('.test'):
            return 'http://app.test'
        elif api_url.endswith('wandb.ai'):
            return 'https://app.wandb.ai'
        else:
            return api_url

    def settings(self, key=None, section=None):
        """The settings overridden from the wandb/settings file.

        Args:
            key (str, optional): If provided only this setting is returned
            section (str, optional): If provided this section of the setting file is
            used, defaults to "default"

        Returns:
            A dict with the current settings

                {
                    "entity": "models",
                    "base_url": "https://api.wandb.ai",
                    "project": None
                }
        """
        if not self._settings:
            self._settings = self.default_settings.copy()
            section = section or self._settings['section']
            try:
                if section in self._settings_parser.sections():
                    for option in self._settings_parser.options(section):
                        self._settings[option] = self._settings_parser.get(
                            section, option)
            except configparser.InterpolationSyntaxError:
                print("WARNING: Unable to parse settings file")
            self._settings["project"] = os.environ.get("WANDB_PROJECT",
                                                       self._settings.get("project"))
            self._settings["entity"] = os.environ.get("WANDB_ENTITY",
                                                      self._settings.get("entity"))
            self._settings["base_url"] = os.environ.get("WANDB_BASE_URL",
                                                        self._settings.get("base_url"))
        return self._settings if key is None else self._settings[key]

    def parse_slug(self, slug, project=None, run=None):
        if slug and "/" in slug:
            parts = slug.split("/")
            project = parts[0]
            run = parts[1]
        else:
            project = project or self.settings().get("project")
            if project is None:
                raise CommError("No default project configured.")
            run = run or slug or os.environ.get("WANDB_RUN")
            if run is None:
                run = "latest"
        return (project, run)

    @normalize_exceptions
    def viewer(self):
        query = gql('''
        query Viewer{
            viewer {
                id
                entity
                teams {
                    edges {
                        node {
                            name
                        }
                    }
                }
            }
        }
        ''')
        res = self.gql(query)
        return res.get('viewer', {})

    @normalize_exceptions
    def list_projects(self, entity=None):
        """Lists projects in W&B scoped by entity.

        Args:
            entity (str, optional): The entity to scope this project to.  Defaults to public models

        Returns:
                [{"id","name","description"}]
        """
        query = gql('''
        query Models($entity: String!) {
            models(first: 10, entityName: $entity) {
                edges {
                    node {
                        id
                        name
                        description
                    }
                }
            }
        }
        ''')
        return self._flatten_edges(self.gql(query, variable_values={
            'entity': entity or self.settings('entity')})['models'])

    @normalize_exceptions
    def list_runs(self, project, entity=None):
        """Lists runs in W&B scoped by project.

        Args:
            project (str): The project to scope the runs to
            entity (str, optional): The entity to scope this project to.  Defaults to public models

        Returns:
                [{"id",name","description"}]
        """
        query = gql('''
        query Buckets($model: String!, $entity: String!) {
            model(name: $model, entityName: $entity) {
                buckets(first: 10) {
                    edges {
                        node {
                            id
                            name
                            description
                        }
                    }
                }
            }
        }
        ''')
        return self._flatten_edges(self.gql(query, variable_values={
            'entity': entity or self.settings('entity'),
            'model': project or self.settings('project')})['model']['buckets'])

    @normalize_exceptions
    def launch_run(self, command, project=None, entity=None, run_id=None):
        """Launch a run in the cloud.

        Args:
            command (str): The command to run
            program (str): The file to run
            project (str): The project to scope the runs to
            entity (str, optional): The entity to scope this project to.  Defaults to public models
            run_id (str, optional): The run_id to scope to

        Returns:
                [{"podName","status"}]
        """
        query = gql('''
        mutation launchRun(
            $entity: String
            $model: String
            $runId: String
            $image: String
            $command: String
            $patch: String
            $cwd: String
            $datasets: [String]
        ) {
            launchRun(input: {id: $runId, entityName: $entity, patch: $patch, modelName: $model,
                image: $image, command: $command, datasets: $datasets, cwd: $cwd}) {
                podName
                status
                runId
            }
        }
        ''')
        patch = BytesIO()
        if self.git.dirty:
            self.git.repo.git.execute(['git', 'diff'], output_stream=patch)
            patch.seek(0)
        cwd = "."
        if self.git.enabled:
            cwd = cwd + os.getcwd().replace(self.git.repo.working_dir, "")
        return self.gql(query, variable_values={
            'entity': entity or self.settings('entity'),
            'model': project or self.settings('project'),
            'command': command,
            'runId': run_id,
            'patch': patch.read().decode("utf8"),
            'cwd': cwd
        })

    @normalize_exceptions
    def run_config(self, project, run=None, entity=None):
        """Get the config for a run

        Args:
            project (str): The project to download, (can include bucket)
            run (str, optional): The run to download
            entity (str, optional): The entity to scope this project to.
        """
        query = gql('''
        query Model($name: String!, $entity: String!, $run: String!) {
            model(name: $name, entityName: $entity) {
                bucket(name: $run) {
                    config
                    commit
                    patch
                }
            }
        }
        ''')

        response = self.gql(query, variable_values={
            'name': project, 'run': run, 'entity': entity
        })
        run = response['model']['bucket']
        commit = run['commit']
        patch = run['patch']
        config = json.loads(run['config'] or '{}')
        return (commit, config, patch)

    def format_project(self, project):
        return re.sub(r'\W+', '-', project.lower()).strip("-_")

    @normalize_exceptions
    def upsert_project(self, project, id=None, description=None, entity=None):
        """Create a new project

        Args:
            project (str): The project to create
            description (str, optional): A description of this project
            entity (str, optional): The entity to scope this project to.
        """
        mutation = gql('''
        mutation UpsertModel($name: String!, $id: String, $entity: String!, $description: String, $repo: String)  {
            upsertModel(input: { id: $id, name: $name, entityName: $entity, description: $description, repo: $repo }) {
                model {
                    name
                    description
                }
            }
        }
        ''')
        response = self.gql(mutation, variable_values={
            'name': self.format_project(project), 'entity': entity or self.settings('entity'),
            'description': description, 'repo': self.git.remote_url, 'id': id})
        return response['upsertModel']['model']

    @normalize_exceptions
    def upsert_run(self, id=None, name=None, project=None, host=None,
                   config=None, description=None, entity=None, state=None,
                   repo=None, job_type=None, program_path=None, commit=None,
                   sweep_name=None):
        """Update a run

        Args:
            id (str, optional): The existing run to update
            name (str, optional): The name of the run to create
            project (str, optional): The name of the project
            config (dict, optional): The latest config params
            description (str, optional): A description of this project
            entity (str, optional): The entity to scope this project to.
            repo (str, optional): Url of the program's repository.
            state (str, optional): State of the program.
            job_type (str, optional): Type of job, e.g 'train'.
            program_path (str, optional): Path to the program.
            commit (str, optional): The Git SHA to associate the run with
        """
        mutation = gql('''
        mutation UpsertBucket(
            $id: String, $name: String,
            $project: String,
            $entity: String!,
            $description: String,
            $commit: String,
            $config: JSONString,
            $host: String,
            $debug: Boolean,
            $program: String,
            $repo: String,
            $jobType: String,
            $state: String,
            $sweep: String
        ) {
            upsertBucket(input: {
                id: $id, name: $name,
                modelName: $project,
                entityName: $entity,
                description: $description,
                config: $config,
                commit: $commit,
                host: $host,
                debug: $debug,
                jobProgram: $program,
                jobRepo: $repo,
                jobType: $jobType,
                state: $state,
                sweep: $sweep
            }) {
                bucket {
                    id
                    name
                    description
                    config
                }
            }
        }
        ''')
        if config is not None:
            config = json.dumps(config)
        if not description:
            description = None
        commit = commit or self.git.last_commit
        response = self.gql(mutation, variable_values={
            'id': id, 'entity': entity or self.settings('entity'), 'name': name, 'project': project,
            'description': description, 'config': config, 'commit': commit,
            'host': host, 'debug': os.getenv('DEBUG'), 'repo': repo, 'program': program_path, 'jobType': job_type,
            'state': state, 'sweep': sweep_name})
        return response['upsertBucket']['bucket']

    @normalize_exceptions
    def upload_urls(self, project, files, run=None, entity=None, description=None):
        """Generate temporary resumeable upload urls

        Args:
            project (str): The project to download
            files (list or dict): The filenames to upload
            run (str, optional): The run to upload to
            entity (str, optional): The entity to scope this project to.  Defaults to wandb models

        Returns:
            (bucket_id, file_info)
            bucket_id: id of bucket we uploaded to
            file_info: A dict of filenames and urls, also indicates if this revision already has uploaded files.
                {
                    'weights.h5': { "url": "https://weights.url" },
                    'model.json': { "url": "https://model.json", "updatedAt": '2013-04-26T22:22:23.832Z', 'md5': 'mZFLkyvTelC5g8XnyQrpOw==' },
                }
        """
        query = gql('''
        query Model($name: String!, $files: [String]!, $entity: String!, $run: String!, $description: String) {
            model(name: $name, entityName: $entity) {
                bucket(name: $run, desc: $description) {
                    id
                    files(names: $files) {
                        edges {
                            node {
                                name
                                url(upload: true)
                                updatedAt
                            }
                        }
                    }
                }
            }
        }
        ''')
        query_result = self.gql(query, variable_values={
            'name': project, 'run': run or self.settings('run'),
            'entity': entity or self.settings('entity'),
            'description': description,
            'files': [file for file in files]
        })

        run = query_result['model']['bucket']
        result = {file['name']
            : file for file in self._flatten_edges(run['files'])}
        return run['id'], result

    @normalize_exceptions
    def download_urls(self, project, run=None, entity=None):
        """Generate download urls

        Args:
            project (str): The project to download
            run (str, optional): The run to upload to
            entity (str, optional): The entity to scope this project to.  Defaults to wandb models

        Returns:
            A dict of extensions and urls

                {
                    'weights.h5': { "url": "https://weights.url", "updatedAt": '2013-04-26T22:22:23.832Z', 'md5': 'mZFLkyvTelC5g8XnyQrpOw==' },
                    'model.json': { "url": "https://model.url", "updatedAt": '2013-04-26T22:22:23.832Z', 'md5': 'mZFLkyvTelC5g8XnyQrpOw==' }
                }
        """
        query = gql('''
        query Model($name: String!, $entity: String!, $run: String!)  {
            model(name: $name, entityName: $entity) {
                bucket(name: $run) {
                    files {
                        edges {
                            node {
                                name
                                url
                                md5
                                updatedAt
                            }
                        }
                    }
                }
            }
        }
        ''')
        query_result = self.gql(query, variable_values={
            'name': project, 'run': run or self.settings('run'),
            'entity': entity or self.settings('entity')})
        files = self._flatten_edges(query_result['model']['bucket']['files'])
        return {file['name']: file for file in files}

    @normalize_exceptions
    def download_file(self, url):
        """Initiate a streaming download

        Args:
            url (str): The url to download

        Returns:
            A tuple of the content length and the streaming response
        """
        response = requests.get(url, stream=True)
        response.raise_for_status()
        return (int(response.headers.get('content-length', 0)), response)

    @normalize_exceptions
    def download_write_file(self, metadata):
        """Download a file from a run and write it to wandb/

        Args:
            metadata (obj): The metadata object for the file to download. Comes from Api.download_urls().

        Returns:
            A tuple of the file's local path and the streaming response. The streaming response is None if the file already existed and was up to date.
        """
        fileName = metadata['name']
        path = os.path.join(__stage_dir__, fileName)
        if self.file_current(fileName, metadata['md5']):
            return path, None

        size, response = self.download_file(metadata['url'])

        with open(path, "wb") as file:
            for data in response.iter_content():
                file.write(data)

        return path, response

    @normalize_exceptions
    def upload_file(self, url, file, callback=None):
        """Uploads a file to W&B with failure resumption

        Args:
            url (str): The url to download
            file (str): The path to the file you want to upload
            callback (:obj:`func`, optional): A callback which is passed the number of
            bytes uploaded since the last time it was called, used to report progress

        Returns:
            The requests library response object
        """
        attempts = 0
        extra_headers = {}
        if os.stat(file.name).st_size == 0:
            raise CommError("%s is an empty file" % file.name)
        while attempts < self.retries:
            try:
                progress = Progress(file, callback=callback)
                response = requests.put(
                    url, data=progress, headers=extra_headers)
                response.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                total = progress.len
                status = self._status_request(url, total)
                if status.status_code == 308:
                    attempts += 1
                    completed = int(status.headers['Range'].split("-")[-1])
                    extra_headers = {
                        'Content-Range': 'bytes {completed}-{total}/{total}'.format(
                            completed=completed,
                            total=total
                        ),
                        'Content-Length': str(total - completed)
                    }
                else:
                    raise e
        return response

    @normalize_exceptions
    def register_agent(self, host, persistent, sweep_id=None, project_name=None):
        """Register a new agent

        Args:
            host (str): hostname
            persistent (bool): long running or oneoff
            sweep (str): sweep id
            project_name: (str): model that contains sweep
        """
        mutation = gql('''
        mutation CreateAgent(
            $host: String!
            $modelName: String!,
            $entityName: String,
            $persistent: Boolean,
            $sweep: String
        ) {
            createAgent(input: {
                host: $host,
                modelName: $modelName,
                entityName: $entityName,
                persistent: $persistent,
                sweep: $sweep,
            }) {
                agent {
                    id
                }
            }
        }
        ''')
        if project_name is None:
            project_name = self.settings('project')
        response = self.gql(mutation, variable_values={
            'host': host,
            'entityName': self.settings("entity"),
            'modelName': project_name,
            'persistent': persistent,
            'sweep': sweep_id})
        return response['createAgent']['agent']

    def agent_heartbeat(self, agent_id, metrics, run_states):
        """Notify server about agent state, receive commands.

        Args:
            agent_id (str): agent_id
            metrics (dict): system metrics
            run_states (dict): run_id: state mapping
        Returns:
            List of commands to execute.
        """
        mutation = gql('''
        mutation Heartbeat(
            $id: String!,
            $metrics: JSONString,
            $runState: JSONString
        ) {
            heartbeat(input: {
                id: $id,
                metrics: $metrics,
                runState: $runState,
                serverRunGen: true
            }) {
                agent {
                    id
                }
                commands
            }
        }
        ''')
        try:
            response = self.gql(mutation, variable_values={
                'id': agent_id,
                'metrics': json.dumps(metrics),
                'runState': json.dumps(run_states)})
        except Exception as e:
            # GQL raises exceptions with stringified python dictionaries :/
            message = ast.literal_eval(e.args[0])["message"]
            logger.error('Error communicating with W&B: %s', message)
            return []
        else:
            return json.loads(response['heartbeat']['commands'])

    @normalize_exceptions
    def upsert_sweep(self, config):
        """Upsert a sweep object.

        Args:
            config (str): sweep config (will be converted to yaml)
        """
        mutation = gql('''
        mutation UpsertSweep(
            $config: String,
            $description: String,
            $entityName: String,
            $modelName: String!
        ) {
            upsertSweep(input: {
                config: $config,
                description: $description,
                entityName: $entityName,
                modelName: $modelName
            }) {
                sweep {
                    name
                }
            }
        }
        ''')
        response = self.gql(mutation, variable_values={
            'config': yaml.dump(config),
            'description': config.get("description"),
            'entityName': self.settings("entity"),
            'modelName': self.settings("project")})
        return response['upsertSweep']['sweep']['name']

    def file_current(self, fname, md5):
        """Checksum a file and compare the md5 with the known md5
        """
        return os.path.isfile(fname) and util.md5_file(fname) == md5

    @normalize_exceptions
    def pull(self, project, run=None, entity=None):
        """Download files from W&B

        Args:
            project (str): The project to download
            run (str, optional): The run to upload to
            entity (str, optional): The entity to scope this project to.  Defaults to wandb models

        Returns:
            The requests library response object
        """
        project, run = self.parse_slug(project, run=run)
        urls = self.download_urls(project, run, entity)
        responses = []
        for fileName in urls:
            _, response = self.download_write_file(urls[fileName])
            if response:
                responses.append(response)

        return responses

    @normalize_exceptions
    def push(self, project, files, run=None, entity=None, description=None, force=True, progress=False):
        """Uploads multiple files to W&B

        Args:
            project (str): The project to upload to
            files (list or dict): The filenames to upload
            run (str, optional): The run to upload to
            entity (str, optional): The entity to scope this project to.  Defaults to wandb models
            description (str, optional): The description of the changes
            force (bool, optional): Whether to prevent push if git has uncommitted changes
            progress (callable, or stream): If callable, will be called with (chunk_bytes,
                total_bytes) as argument else if True, renders a progress bar to stream.

        Returns:
            The requests library response object
        """
        project, run = self.parse_slug(project, run=run)
        # Only tag if enabled
        if self.settings("git_tag"):
            self.tag_and_push(run, description, force)
        run_id, result = self.upload_urls(
            project, files, run, entity, description)
        responses = []
        for file_name, file_info in result.items():
            try:
                open_file = files[file_name] if isinstance(
                    files, dict) else open(file_name, "rb")
            except IOError:
                print("%s does not exist" % file_name)
                continue
            if progress:
                if hasattr(progress, '__call__'):
                    responses.append(self.upload_file(
                        file_info['url'], open_file, progress))
                else:
                    length = os.fstat(open_file.fileno()).st_size
                    with click.progressbar(file=progress, length=length, label='Uploading file: %s' % (file_name),
                                           fill_char=click.style('&', fg='green')) as bar:
                        responses.append(self.upload_file(
                            file_info['url'], open_file, lambda bites, _: bar.update(bites)))
            else:
                responses.append(self.upload_file(file_info['url'], open_file))
            open_file.close()
        return responses

    def get_file_stream_api(self):
        if not self._file_stream_api:
            settings = self.settings()
            if self._current_run_id is None:
                raise UsageError(
                    'Must have a current run to use file stream API.')
            self._file_stream_api = FileStreamApi(
                self.api_key, self.user_agent, settings['base_url'],
                settings['entity'], settings['project'], self._current_run_id)
        return self._file_stream_api

    def tag_and_push(self, name, description, force=True):
        if self.git.enabled and not self.tagged:
            self.tagged = True
            # TODO: this is getting called twice...
            print("Tagging your git repo...")
            if not force and self.git.dirty:
                raise CommError(
                    "You have un-committed changes. Use the force flag or commit your changes.")
            elif self.git.dirty and os.path.exists(__stage_dir__):
                self.git.repo.git.execute(['git', 'diff'], output_stream=open(
                    os.path.join(__stage_dir__, 'diff.patch'), 'wb'))
            self.git.tag(name, description)
            result = self.git.push(name)
            if(result is None or len(result) is None):
                print("Unable to push git tag.")

    def _status_request(self, url, length):
        """Ask google how much we've uploaded"""
        return requests.put(
            url=url,
            headers={'Content-Length': '0',
                     'Content-Range': 'bytes */%i' % length}
        )

    def _flatten_edges(self, response):
        """Return an array from the nested graphql relay structure"""
        return [node['node'] for node in response['edges']]


Chunk = collections.namedtuple('Chunk', ('filename', 'data'))


class DefaultFilePolicy(object):
    def __init__(self):
        self._chunk_id = 0

    def process_chunks(self, chunks):
        chunk_id = self._chunk_id
        self._chunk_id += len(chunks)
        return {
            'offset': chunk_id,
            'content': [c.data for c in chunks]
        }


class CRDedupeFilePolicy(object):
    def __init__(self):
        self._chunk_id = 0

    def process_chunks(self, chunks):
        content = []
        for line in [c.data for c in chunks]:
            if content and content[-1].endswith('\r'):
                content[-1] = line
            else:
                content.append(line)
        chunk_id = self._chunk_id
        self._chunk_id += len(content)
        if content and content[-1].endswith('\r'):
            self._chunk_id -= 1
        return {
            'offset': chunk_id,
            'content': content
        }


class BinaryFilePolicy(object):
    def __init__(self):
        self._offset = 0

    def process_chunks(self, chunks):
        data = b''.join([c.data for c in chunks])
        enc = base64.b64encode(data).decode('ascii')
        offset = self._offset
        self._offset += len(data)
        return {
            'offset': self._offset,
            'content': enc,
            'encoding': 'base64'
        }


class FileStreamApi(object):
    """Pushes chunks of files to our streaming endpoint.

    This class is used as a singleton. It has a thread that serializes access to
    the streaming endpoint and performs rate-limiting and batching.

    TODO: Differentiate between binary/text encoding.
    """
    Finish = collections.namedtuple('Finish', ('exitcode'))

    HTTP_TIMEOUT = 10
    RATE_LIMIT_SECONDS = 1
    HEARTBEAT_INTERVAL_SECONDS = 15
    MAX_ITEMS_PER_PUSH = 10000

    def __init__(self, api_key, user_agent, base_url, entity, project, run_id):
        self._endpoint = "{base}/{entity}/{project}/{run}/file_stream".format(
            base=base_url,
            entity=entity,
            project=project,
            run=run_id)
        self._client = requests.Session()
        self._client.auth = ('api', api_key)
        self._client.timeout = self.HTTP_TIMEOUT
        self._client.headers.update({
            'User-Agent': user_agent,
        })
        self._file_policies = {}
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._thread_body)
        # It seems we need to make this a daemon thread to get sync.py's atexit handler to run, which
        # cleans this thread up.
        self._thread.daemon = True
        self._thread.start()

    def set_file_policy(self, filename, file_policy):
        self._file_policies[filename] = file_policy

    def _read_queue(self):
        # called from the push thread (_thread_body), this does an initial read
        # that'll block for up to RATE_LIMIT_SECONDS. Then it tries to read
        # as much out of the queue as it can. We do this because the http post
        # to the server happens within _thread_body, and can take longer than
        # our rate limit. So next time we get a chance to read the queue we want
        # read all the stuff that queue'd up since last time.
        #
        # If we have more than MAX_ITEMS_PER_PUSH in the queue then the push thread
        # will get behind and data will buffer up in the queue.
        return util.read_many_from_queue(
            self._queue, self.MAX_ITEMS_PER_PUSH, self.RATE_LIMIT_SECONDS)

    def _thread_body(self):
        posted_data_time = time.time()
        posted_anything_time = time.time()
        ready_chunks = []
        finished = None
        while finished is None:
            items = self._read_queue()
            for item in items:
                if isinstance(item, self.Finish):
                    finished = item
                else:
                    # item is Chunk
                    ready_chunks.append(item)

            cur_time = time.time()

            if ready_chunks and cur_time - posted_data_time > self.RATE_LIMIT_SECONDS:
                posted_data_time = cur_time
                posted_anything_time = cur_time
                self._send(ready_chunks)
                ready_chunks = []

            if cur_time - posted_anything_time > self.HEARTBEAT_INTERVAL_SECONDS:
                posted_anything_time = cur_time
                util.request_with_retry(self._client.post,
                                        self._endpoint, json={'complete': False, 'failed': False})
        # post the final close message. (item is self.Finish instance now)
        util.request_with_retry(self._client.post,
                                self._endpoint, json={'complete': True, 'exitcode': int(finished.exitcode)})

    def _send(self, chunks):
        # create files dict. dict of <filename: chunks> pairs where chunks is a list of
        # [chunk_id, chunk_data] tuples (as lists since this will be json).
        files = {}
        # Groupby needs group keys to be consecutive, so sort first.
        chunks.sort(key=lambda c: c.filename)
        for filename, file_chunks in itertools.groupby(chunks, lambda c: c.filename):
            file_chunks = list(file_chunks)  # groupby returns iterator
            if filename not in self._file_policies:
                self._file_policies[filename] = DefaultFilePolicy()
            files[filename] = self._file_policies[filename].process_chunks(
                file_chunks)

        util.request_with_retry(
            self._client.post, self._endpoint, json={'files': files})

    def push(self, filename, data):
        """Push a chunk of a file to the streaming endpoint.

        Args:
            filename: Name of file that this is a chunk of.
            chunk_id: TODO: change to 'offset'
            chunk: File data.
        """
        self._queue.put(Chunk(filename, data))

    def finish(self, exitcode):
        """Cleans up.

        Anything pushed after finish will be dropped.

        Args:
            exitcode: The exitcode of the watched process.
        """
        self._queue.put(self.Finish(exitcode))
        self._thread.join()
