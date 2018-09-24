from gql import Client, gql
from gql.client import RetryError
from gql.transport.requests import RequestsHTTPTransport
import datetime
import os
import requests
import ast
import os
import json
import yaml
import re
import click
import logging
import requests
from six import BytesIO
from six.moves import configparser
import socket
import subprocess
import time
import sys
import random

from six import b

import wandb
from wandb import __version__, wandb_dir, Error
from wandb import env
from wandb.git_repo import GitRepo
from wandb import retry
from wandb import util
from wandb.apis import FileStreamApi, normalize_exceptions, CommError, Progress, UsageError

logger = logging.getLogger(__name__)


class Api(object):
    """W&B Internal Api wrapper

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

    def __init__(self, default_settings=None, load_settings=True, retry_timedelta=datetime.timedelta(days=1)):
        self.default_settings = {
            'section': "default",
            'entity': "models",
            'run': "latest",
            'git_remote': "origin",
            'git_tag': False,
            'ignore_globs': [],
            'base_url': "https://api.wandb.ai"
        }
        self.retry_timedelta = retry_timedelta
        self.default_settings.update(default_settings or {})
        self._settings = None
        self.retry_uploads = 10
        self.settings_parser = configparser.ConfigParser()
        self.tagged = False
        self.update_available = False
        if load_settings:
            potential_settings_paths = [
                os.path.expanduser('~/.wandb/settings')
            ]
            potential_settings_paths.append(
                os.path.join(wandb_dir(), 'settings'))
            files = self.settings_parser.read(potential_settings_paths)
            self.settings_file = files[0] if len(files) > 0 else "Not found"
        else:
            self.settings_file = "Not found"
        self.git = GitRepo(remote=self.settings("git_remote"))
        # Mutable settings set by the _file_stream_api
        self.dynamic_settings = {
            'system_sample_seconds': 2,
            'system_samples': 15,
            'heartbeat_seconds': 30,
        }
        self.client = Client(
            transport=RequestsHTTPTransport(
                headers={'User-Agent': self.user_agent},
                use_json=True,
                # this timeout won't apply when the DNS lookup fails. in that case, it will be 60s
                # https://bugs.python.org/issue22889
                timeout=self.HTTP_TIMEOUT,
                auth=("api", self.api_key),
                url='%s/graphql' % self.settings('base_url')
            )
        )
        self.gql = retry.Retry(self.client.execute, retry_timedelta=retry_timedelta,
                               retryable_exceptions=(RetryError, requests.RequestException))
        self._current_run_id = None
        self._file_stream_api = None

    def disabled(self):
        try:
            return self.settings_parser.get('default', 'disabled')
        except configparser.Error:
            return False

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
        if not self.git.enabled:
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

    def repo_remote_url(self):
        # TODO: better failure handling
        if self.git.enabled:
            root = self.git.root
            remote_url = self.git.remote_url
        else:
            host = socket.gethostname()
            root = os.path.abspath(os.getcwd())
            remote_url = 'file://%s%s' % (host, root)

        return remote_url

    def set_current_run_id(self, run_id):
        self._current_run_id = run_id

    @property
    def current_run_id(self):
        return self._current_run_id

    @property
    def user_agent(self):
        return 'W&B Internal Client %s' % __version__

    @property
    def api_key(self):
        auth = requests.utils.get_netrc_auth(self.api_url)
        key = None
        if auth:
            key = auth[-1]
        # Environment should take precedence
        if os.getenv("WANDB_API_KEY"):
            key = os.environ["WANDB_API_KEY"]
        return key

    @property
    def api_url(self):
        return self.settings('base_url')

    @property
    def app_url(self):
        api_url = self.api_url
        if api_url.endswith('.test') or self.settings().get("dev_prod"):
            return 'http://app.test'
        elif api_url.endswith('wandb.ai'):
            return api_url.replace('api.', 'app.')
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
                if section in self.settings_parser.sections():
                    for option in self.settings_parser.options(section):
                        self._settings[option] = self.settings_parser.get(
                            section, option)
            except configparser.InterpolationSyntaxError:
                print("WARNING: Unable to parse settings file")
            self._settings["project"] = env.get_project(
                self._settings.get("project"))
            self._settings["entity"] = env.get_entity(
                self._settings.get("entity"))
            self._settings["base_url"] = env.get_base_url(
                self._settings.get("base_url"))
            self._settings["ignore_globs"] = env.get_ignore(
                self._settings.get("ignore_globs")
            )

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
            run = run or slug or env.get_run()
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

    @normalize_exceptions
    def run_resume_status(self, entity, project, name):
        """Check if a run exists and get resume information.

        Args:
            project (str): The project to download, (can include bucket)
            run (str, optional): The run to download
            entity (str, optional): The entity to scope this project to.
        """
        query = gql('''
        query Model($project: String!, $entity: String!, $name: String!) {
            model(name: $project, entityName: $entity) {
                bucket(name: $name, missingOk: true) {
                    id
                    name
                    logLineCount
                    historyLineCount
                    eventsLineCount
                    historyTail
                    eventsTail
                }
            }
        }
        ''')

        response = self.gql(query, variable_values={
            'entity': entity, 'project': project, 'name': name,
        })
        run = response['model']['bucket']
        return run

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
                   sweep_name=None, summary_metrics=None, num_retries=None):
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
            summary_metrics (str, optional): The JSON summary metrics
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
            $sweep: String,
            $summaryMetrics: JSONString,
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
                sweep: $sweep,
                summaryMetrics: $summaryMetrics,
            }) {
                bucket {
                    id
                    name
                    description
                    config
                }
                updateAvailable
            }
        }
        ''')
        if config is not None:
            config = json.dumps(config)
        if not description:
            description = None

        kwargs = {}
        if num_retries is not None:
            kwargs['num_retries'] = num_retries

        variable_values = {
            'id': id, 'entity': entity or self.settings('entity'), 'name': name, 'project': project,
            'description': description, 'config': config, 'commit': commit,
            'host': host, 'debug': env.get_debug(), 'repo': repo, 'program': program_path, 'jobType': job_type,
            'state': state, 'sweep': sweep_name, 'summaryMetrics': summary_metrics
        }

        response = self.gql(
            mutation, variable_values=variable_values, **kwargs)

        self.update_available = response['upsertBucket']['updateAvailable']
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
        result = {file['name']: file for file in self._flatten_edges(run['files'])}
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
        return {file['name']: file for file in files if file}

    @normalize_exceptions
    def download_url(self, project, file_name, run=None, entity=None):
        """Generate download urls

        Args:
            project (str): The project to download
            file_name (str): The name of the file to download
            run (str, optional): The run to upload to
            entity (str, optional): The entity to scope this project to.  Defaults to wandb models

        Returns:
            A dict of extensions and urls

                { "url": "https://weights.url", "updatedAt": '2013-04-26T22:22:23.832Z', 'md5': 'mZFLkyvTelC5g8XnyQrpOw==' }

        """
        query = gql('''
        query Model($name: String!, $fileName: String!, $entity: String!, $run: String!)  {
            model(name: $name, entityName: $entity) {
                bucket(name: $run) {
                    files(names: [$fileName]) {
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
            'name': project, 'run': run or self.settings('run'), 'fileName': file_name,
            'entity': entity or self.settings('entity')})
        files = self._flatten_edges(query_result['model']['bucket']['files'])
        return files[0] if len(files) > 0 and files[0].get('updatedAt') else None

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
    def download_write_file(self, metadata, out_dir=None):
        """Download a file from a run and write it to wandb/

        Args:
            metadata (obj): The metadata object for the file to download. Comes from Api.download_urls().

        Returns:
            A tuple of the file's local path and the streaming response. The streaming response is None if the file already existed and was up to date.
        """
        fileName = metadata['name']
        path = os.path.join(out_dir or wandb_dir(), fileName)
        if self.file_current(fileName, metadata['md5']):
            return path, None

        size, response = self.download_file(metadata['url'])

        with open(path, "wb") as file:
            for data in response.iter_content(chunk_size=1024):
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
        while attempts < self.retry_uploads:
            try:
                progress = Progress(file, callback=callback)
                response = requests.put(
                    url, data=progress, headers=extra_headers)
                response.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                total = progress.len
                status = self._status_request(url, total)
                attempts += 1
                if status.status_code == 308:
                    if status.headers.get("Range"):
                        completed = int(status.headers['Range'].split("-")[-1])
                        extra_headers = {
                            'Content-Range': 'bytes {completed}-{total}/{total}'.format(
                                completed=completed,
                                total=total
                            ),
                            'Content-Length': str(total - completed)
                        }
                elif status.status_code in (500, 502, 503, 504):
                    time.sleep(random.randint(1, 10))
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
                # To handle Windows paths
                # TODO: this doesn't handle absolute paths...
                normal_name = os.path.join(*file_name.split("/"))
                open_file = files[normal_name] if isinstance(
                    files, dict) else open(normal_name, "rb")
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
        """This creates a new file pusher thread.  Call start to initiate the thread that talks to W&B"""
        if not self._file_stream_api:
            if self._current_run_id is None:
                raise UsageError(
                    'Must have a current run to use file stream API.')
            self._file_stream_api = FileStreamApi(self, self._current_run_id)
        return self._file_stream_api

    def tag_and_push(self, name, description, force=True):
        if self.git.enabled and not self.tagged:
            self.tagged = True
            # TODO: this is getting called twice...
            print("Tagging your git repo...")
            if not force and self.git.dirty:
                raise CommError(
                    "You have un-committed changes. Use the force flag or commit your changes.")
            elif self.git.dirty and os.path.exists(wandb_dir()):
                self.git.repo.git.execute(['git', 'diff'], output_stream=open(
                    os.path.join(wandb_dir(), 'diff.patch'), 'wb'))
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
