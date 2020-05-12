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
import socket
import time
import sys
import random
import traceback

if os.name == 'posix' and sys.version_info[0] < 3:
    import subprocess32 as subprocess
else:
    import subprocess

import six
from six import b
from six import BytesIO
import wandb
from wandb import __version__, wandb_dir, Error
from wandb import env
from wandb.git_repo import GitRepo
from wandb.settings import Settings
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

    HTTP_TIMEOUT = env.get_http_timeout(10)

    def __init__(self, default_settings=None, load_settings=True, retry_timedelta=datetime.timedelta(days=1), environ=os.environ):
        self._environ = environ
        self.default_settings = {
            'section': "default",
            'run': "latest",
            'git_remote': "origin",
            'ignore_globs': [],
            'base_url': "https://api.wandb.ai"
        }
        self.retry_timedelta = retry_timedelta
        self.default_settings.update(default_settings or {})
        self.retry_uploads = 10
        self._settings = Settings(load_settings=load_settings)
        self.git = GitRepo(remote=self.settings("git_remote"))
        # Mutable settings set by the _file_stream_api
        self.dynamic_settings = {
            'system_sample_seconds': 2,
            'system_samples': 15,
            'heartbeat_seconds': 30,
        }
        self.client = Client(
            transport=RequestsHTTPTransport(
                headers={
                    'User-Agent': self.user_agent,
                    'X-WANDB-USERNAME': env.get_username(env=self._environ),
                    'X-WANDB-USER-EMAIL': env.get_user_email(env=self._environ)},
                use_json=True,
                # this timeout won't apply when the DNS lookup fails. in that case, it will be 60s
                # https://bugs.python.org/issue22889
                timeout=self.HTTP_TIMEOUT,
                auth=("api", self.api_key or ""),
                url='%s/graphql' % self.settings('base_url')
            )
        )
        self.gql = retry.Retry(self.execute,
                               retry_timedelta=retry_timedelta,
                               check_retry_fn=util.no_retry_auth,
                               retryable_exceptions=(RetryError, requests.RequestException))
        self._current_run_id = None
        self._file_stream_api = None

    def reauth(self):
        """Ensures the current api key is set in the transport"""
        self.client.transport.auth = ("api", self.api_key or "")

    def relocate(self):
        """Ensures the current api points to the right server"""
        self.client.transport.url = '%s/graphql' % self.settings('base_url')

    def execute(self, *args, **kwargs):
        """Wrapper around execute that logs in cases of failure."""
        try:
            return self.client.execute(*args, **kwargs)
        except requests.exceptions.HTTPError as err:
            res = err.response
            logger.error("%s response executing GraphQL." % res.status_code)
            logger.error(res.text)
            self.display_gorilla_error_if_found(res)
            six.reraise(*sys.exc_info())

    def display_gorilla_error_if_found(self, res):
        try:
            data = res.json()
        except ValueError:
            return

        if 'errors' in data and isinstance(data['errors'], list):
            for err in data['errors']:
                if not err.get('message'):
                    continue
                wandb.termerror('Error while calling W&B API: {} ({})'.format(err['message'], res))

    def disabled(self):
        return self._settings.get(Settings.DEFAULT_SECTION, 'disabled', fallback=False)

    def sync_spell(self, run, env=None):
        """Syncs this run with spell"""
        try:
            env = env or os.environ
            run.config._set_wandb("spell_url", env.get("SPELL_RUN_URL"))
            run.config.persist()
            try:
                url = run.get_url()
            except CommError as e:
                wandb.termerror("Unable to register run with spell.run: %s" % e.message)
                return False
            return requests.put(env.get("SPELL_API_URL", "https://api.spell.run") + "/wandb_url", json={
                "access_token": env.get("WANDB_ACCESS_TOKEN"),
                "url": url
            }, timeout=2)
        except requests.RequestException:
            return False

    def save_pip(self, out_dir):
        """Saves the current working set of pip packages to requirements.txt"""
        try:
            import pkg_resources

            installed_packages = [d for d in iter(pkg_resources.working_set)]
            installed_packages_list = sorted(
                ["%s==%s" % (i.key, i.version) for i in installed_packages]
            )
            with open(os.path.join(out_dir, 'requirements.txt'), 'w') as f:
                f.write("\n".join(installed_packages_list))
        except Exception as e:
            logger.error("Error saving pip packages")

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
                            ['git', 'diff', '--submodule=diff', 'HEAD'], stdout=patch, cwd=root, timeout=5)
                else:
                    with open(patch_path, 'wb') as patch:
                        subprocess.check_call(
                            ['git', 'diff', 'HEAD'], stdout=patch, cwd=root, timeout=5)

            upstream_commit = self.git.get_upstream_fork_point()
            if upstream_commit and upstream_commit != self.git.repo.head.commit:
                sha = upstream_commit.hexsha
                upstream_patch_path = os.path.join(
                    out_dir, 'upstream_diff_{}.patch'.format(sha))
                if self.git.has_submodule_diff:
                    with open(upstream_patch_path, 'wb') as upstream_patch:
                        subprocess.check_call(
                            ['git', 'diff', '--submodule=diff', sha], stdout=upstream_patch, cwd=root, timeout=5)
                else:
                    with open(upstream_patch_path, 'wb') as upstream_patch:
                        subprocess.check_call(
                            ['git', 'diff', sha], stdout=upstream_patch, cwd=root, timeout=5)
        # TODO: A customer saw `ValueError: Reference at 'refs/remotes/origin/foo' does not exist`
        # so we now catch ValueError.  Catching this error feels too generic.
        except (ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error('Error generating diff: %s' % e)

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
        if self._environ.get(env.API_KEY):
            key = self._environ.get(env.API_KEY)
        return key

    @property
    def api_url(self):
        return self.settings('base_url')

    @property
    def app_url(self):
        api_url = self.api_url
        # Development
        if api_url.endswith('.test') or self.settings().get("dev_prod"):
            return 'http://app.wandb.test'
        # On-prem VM
        if api_url.endswith(':11001'):
            return api_url.replace(':11001', ':11000')
        # Normal
        if api_url.startswith('https://api.'):
            return api_url.replace('api.', 'app.')
        # Unexpected
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
        result = self.default_settings.copy()
        result.update(self._settings.items(section=section))
        result.update({
            'entity': env.get_entity(
                self._settings.get(Settings.DEFAULT_SECTION, "entity", fallback=result.get('entity')),
                env=self._environ),
            'project': env.get_project(
                self._settings.get(Settings.DEFAULT_SECTION, "project", fallback=result.get('project')),
                env=self._environ),
            'base_url': env.get_base_url(
                self._settings.get(Settings.DEFAULT_SECTION, "base_url", fallback=result.get('base_url')),
                env=self._environ),
            'ignore_globs': env.get_ignore(
                self._settings.get(Settings.DEFAULT_SECTION, "ignore_globs", fallback=result.get('ignore_globs')),
                env=self._environ),
        })
        # Remove trailing slash and ensure protocol
        result['base_url'] = result['base_url'].strip("/")
        if not result['base_url'].startswith("http"):
            result['base_url'] = "https://"+result['base_url']

        return result if key is None else result[key]

    def clear_setting(self, key, globally=False, persist=False):
        self._settings.clear(Settings.DEFAULT_SECTION, key, globally=globally, persist=persist)

    def set_setting(self, key, value, globally=False, persist=False):
        """Sets setting, optionally globally.  By default we do not persist the setting to disk"""
        self._settings.set(Settings.DEFAULT_SECTION, key, value, globally=globally, persist=persist)
        if key == 'entity':
            env.set_entity(value, env=self._environ)
        elif key == 'project':
            env.set_project(value, env=self._environ)
        elif key == 'base_url':
            self.relocate()

    def parse_slug(self, slug, project=None, run=None):
        if slug and "/" in slug:
            parts = slug.split("/")
            project = parts[0]
            run = parts[1]
        else:
            project = project or self.settings().get("project")
            if project is None:
                raise CommError("No default project configured.")
            run = run or slug or env.get_run(env=self._environ)
            if run is None:
                run = "latest"
        return (project, run)

    @normalize_exceptions
    def viewer(self):
        query = gql('''
        query Viewer{
            viewer {
                id
                flags
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
        return res.get('viewer') or {}

    @normalize_exceptions
    def list_projects(self, entity=None):
        """Lists projects in W&B scoped by entity.

        Args:
            entity (str, optional): The entity to scope this project to.

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
    def project(self, project, entity=None):
        """Retrive project

        Args:
            project (str): The project to get details for
            entity (str, optional): The entity to scope this project to.

        Returns:
                [{"id","name","repo","dockerImage","description"}]
        """
        query = gql('''
        query Models($entity: String, $project: String!) {
            model(name: $project, entityName: $entity) {
                id
                name
                repo
                dockerImage
                description
            }
        }
        ''')
        return self.gql(query, variable_values={
            'entity': entity, 'project': project})['model']

    @normalize_exceptions
    def sweep(self, sweep, specs, project=None, entity=None):
        """Retrieve sweep.

        Args:
            sweep (str): The sweep to get details for
            specs (str): history specs
            project (str, optional): The project to scope this sweep to.
            entity (str, optional): The entity to scope this sweep to.

        Returns:
                [{"id","name","repo","dockerImage","description"}]
        """
        query = gql('''
        query Models($entity: String, $project: String!, $sweep: String!, $specs: [JSONString!]!) {
            model(name: $project, entityName: $entity) {
                sweep(sweepName: $sweep) {
                    id
                    name
                    method
                    state
                    description
                    config
                    createdAt
                    heartbeatAt
                    updatedAt
                    earlyStopJobRunning
                    bestLoss
                    controller
                    scheduler
                    runs {
                        edges {
                            node {
                                name
                                state
                                config
                                exitcode
                                heartbeatAt
                                shouldStop
                                failed
                                stopped
                                running
                                summaryMetrics
                                sampledHistory(specs: $specs)
                            }
                        }
                    }
                }
            }
        }
        ''')
        entity = entity or self.settings('entity')
        project = project or self.settings('project')
        response = self.gql(query, variable_values={'entity': entity,
                                                    'project': project, 'sweep': sweep, 'specs': specs})
        if response['model'] is None or response['model']['sweep'] is None:
            raise ValueError("Sweep {}/{}/{} not found".format(entity, project, sweep) )
        data = response['model']['sweep']
        if data:
            data['runs'] = self._flatten_edges(data['runs'])
        return data

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
                            displayName
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
        """Get the relevant configs for a run

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
                    files(names: ["wandb-metadata.json"]) {
                        edges {
                            node {
                                url
                            }
                        }
                    }
                }
            }
        }
        ''')

        response = self.gql(query, variable_values={
            'name': project, 'run': run, 'entity': entity
        })
        if response['model'] == None:
            raise ValueError("Run {}/{}/{} not found".format(entity, project, run) )
        run = response['model']['bucket']
        commit = run['commit']
        patch = run['patch']
        config = json.loads(run['config'] or '{}')
        if len(run['files']['edges']) > 0:
            url = run['files']['edges'][0]['node']['url']
            res = requests.get(url)
            res.raise_for_status()
            metadata = res.json()
        else:
            metadata = {}
        return (commit, config, patch, metadata)

    @normalize_exceptions
    def run_resume_status(self, entity, project_name, name):
        """Check if a run exists and get resume information.

        Args:
            entity (str, optional): The entity to scope this project to.
            project_name (str): The project to download, (can include bucket)
            run (str, optional): The run to download
        """
        query = gql('''
        query Model($project: String!, $entity: String, $name: String!) {
            model(name: $project, entityName: $entity) {
                id
                name
                entity {
                    id
                    name
                }

                bucket(name: $name, missingOk: true) {
                    id
                    name
                    summaryMetrics
                    displayName
                    logLineCount
                    historyLineCount
                    eventsLineCount
                    historyTail
                    eventsTail
                    config
                }
            }
        }
        ''')

        response = self.gql(query, variable_values={
            'entity': entity, 'project': project_name, 'name': name,
        })

        if 'model' not in response or 'bucket' not in (response['model'] or {}):
            return None

        project = response['model']
        self.set_setting('project', project_name)
        if 'entity' in project:
            self.set_setting('entity', project['entity']['name'])

        return project['bucket']

    @normalize_exceptions
    def check_stop_requested(self, project_name, entity_name, run_id):
        query = gql('''
        query Model($projectName: String, $entityName: String, $runId: String!) {
            project(name:$projectName, entityName:$entityName) {
                run(name:$runId) {
                    stopped
                }
            }
        }
        ''')

        response = self.gql(query, variable_values={
            'projectName': project_name, 'entityName': entity_name, 'runId': run_id,
        })

        project = response.get('project', None)
        if not project:
            return False
        run = project.get('run', None)
        if not run:
            return False

        return run['stopped']

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
                   group=None, tags=None,
                   config=None, description=None, entity=None, state=None,
                   display_name=None, notes=None,
                   repo=None, job_type=None, program_path=None, commit=None,
                   sweep_name=None, summary_metrics=None, num_retries=None):
        """Update a run

        Args:
            id (str, optional): The existing run to update
            name (str, optional): The name of the run to create
            group (str, optional): Name of the group this run is a part of
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
            $groupName: String,
            $description: String,
            $displayName: String,
            $notes: String,
            $commit: String,
            $config: JSONString,
            $host: String,
            $debug: Boolean,
            $program: String,
            $repo: String,
            $jobType: String,
            $state: String,
            $sweep: String,
            $tags: [String!],
            $summaryMetrics: JSONString,
        ) {
            upsertBucket(input: {
                id: $id,
                name: $name,
                groupName: $groupName,
                modelName: $project,
                entityName: $entity,
                description: $description,
                displayName: $displayName,
                notes: $notes,
                config: $config,
                commit: $commit,
                host: $host,
                debug: $debug,
                jobProgram: $program,
                jobRepo: $repo,
                jobType: $jobType,
                state: $state,
                sweep: $sweep,
                tags: $tags,
                summaryMetrics: $summaryMetrics,
            }) {
                bucket {
                    id
                    name
                    displayName
                    description
                    config
                    project {
                        id
                        name
                        entity {
                            id
                            name
                        }
                    }
                }
            }
        }
        ''')
        if config is not None:
            config = json.dumps(config)
        if not description or description.isspace():
            description = None

        kwargs = {}
        if num_retries is not None:
            kwargs['num_retries'] = num_retries

        variable_values = {
            'id': id, 'entity': entity or self.settings('entity'), 'name': name, 'project': project,
            'groupName': group, 'tags': tags,
            'description': description, 'config': config, 'commit': commit,
            'displayName': display_name, 'notes': notes,
            'host': None if self.settings().get('anonymous') == 'true' else host,
            'debug': env.is_debug(env=self._environ), 'repo': repo, 'program': program_path, 'jobType': job_type,
            'state': state, 'sweep': sweep_name, 'summaryMetrics': summary_metrics
        }

        response = self.gql(
            mutation, variable_values=variable_values, **kwargs)

        run = response['upsertBucket']['bucket']
        project = run.get('project')
        if project:
            self.set_setting('project', project['name'])
            entity = project.get('entity')
            if entity:
                self.set_setting('entity', entity['name'])

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
                        uploadHeaders
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
        run_id = run or self.settings('run')
        entity = entity or self.settings('entity')
        query_result = self.gql(query, variable_values={
            'name': project, 'run': run_id,
            'entity': entity,
            'description': description,
            'files': [file for file in files]
        })

        run = query_result['model']['bucket']
        if run:
            result = {file['name']: file for file in self._flatten_edges(run['files'])}
            return run['id'], run['files']['uploadHeaders'], result
        else:
            raise CommError("Run does not exist {}/{}/{}.".format(entity, project, run_id))

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
        if query_result['model']:
            files = self._flatten_edges(query_result['model']['bucket']['files'])
            return files[0] if len(files) > 0 and files[0].get('updatedAt') else None
        else:
            return None

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

    def upload_file(self, url, file, callback=None, extra_headers={}):
        """Uploads a file to W&B with failure resumption

        Args:
            url (str): The url to download
            file (str): The path to the file you want to upload
            callback (:obj:`func`, optional): A callback which is passed the number of
            bytes uploaded since the last time it was called, used to report progress

        Returns:
            The requests library response object
        """
        extra_headers = extra_headers.copy()
        response = None
        progress = Progress(file, callback=callback)
        if progress.len == 0:
            raise CommError("%s is an empty file" % file.name)
        try:
            response = requests.put(
                url, data=progress, headers=extra_headers)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            status_code = e.response.status_code if e.response != None else 0
            # Retry errors from cloud storage or local network issues
            if status_code in (308, 409, 429, 500, 502, 503, 504) or isinstance(e, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
                util.sentry_reraise(retry.TransientException(exc=e))
            else:
                util.sentry_reraise(e)

        return response

    upload_file_retry = normalize_exceptions(retry.retriable(num_retries=5)(upload_file))

    @normalize_exceptions
    def register_agent(self, host, sweep_id=None, project_name=None, entity=None):
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
            $projectName: String!,
            $entityName: String!,
            $sweep: String!
        ) {
            createAgent(input: {
                host: $host,
                projectName: $projectName,
                entityName: $entityName,
                sweep: $sweep,
            }) {
                agent {
                    id
                }
            }
        }
        ''')
        if entity is None:
            entity = self.settings("entity")
        if project_name is None:
            project_name = self.settings('project')

        # don't retry on validation or not found errors
        def no_retry_4xx(e):
            if not isinstance(e, requests.HTTPError):
                return True
            if not(e.response.status_code >= 400 and e.response.status_code < 500):
                return True
            body = json.loads(e.response.content)
            raise UsageError(body['errors'][0]['message'])

        response = self.gql(mutation, variable_values={
            'host': host,
            'entityName': entity,
            'projectName': project_name,
            'sweep': sweep_id}, check_retry_fn=no_retry_4xx)
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
            $id: ID!,
            $metrics: JSONString,
            $runState: JSONString
        ) {
            agentHeartbeat(input: {
                id: $id,
                metrics: $metrics,
                runState: $runState
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
            return json.loads(response['agentHeartbeat']['commands'])

    @normalize_exceptions
    def upsert_sweep(self, config, controller=None, scheduler=None, obj_id=None, project=None, entity=None):
        """Upsert a sweep object.

        Args:
            config (str): sweep config (will be converted to yaml)
        """
        project_query = '''
                    project {
                        id
                        name
                        entity {
                            id
                            name
                        }
                    }
        '''
        mutation_str = '''
        mutation UpsertSweep(
            $id: ID,
            $config: String,
            $description: String,
            $entityName: String!,
            $projectName: String!,
            $controller: JSONString,
            $scheduler: JSONString
        ) {
            upsertSweep(input: {
                id: $id,
                config: $config,
                description: $description,
                entityName: $entityName,
                projectName: $projectName,
                controller: $controller,
                scheduler: $scheduler
            }) {
                sweep {
                    name
                    _PROJECT_QUERY_
                }
            }
        }
        '''
        # FIXME(jhr): we need protocol versioning to know schema is not supported
        # for now we will just try both new and old query
        mutation_new = gql(mutation_str.replace("_PROJECT_QUERY_", project_query))
        mutation_old = gql(mutation_str.replace("_PROJECT_QUERY_", ""))

        # don't retry on validation errors
        # TODO(jhr): generalize error handling routines
        def no_retry_4xx(e):
            if not isinstance(e, requests.HTTPError):
                return True
            if not(e.response.status_code >= 400 and e.response.status_code < 500):
                return True
            body = json.loads(e.response.content)
            raise UsageError(body['errors'][0]['message'])

        for mutation in mutation_new, mutation_old:
            try:
                response = self.gql(mutation, variable_values={
                    'id': obj_id,
                    'config': yaml.dump(config),
                    'description': config.get("description"),
                    'entityName': entity or self.settings("entity"),
                    'projectName': project or self.settings("project"),
                    'controller': controller,
                    'scheduler': scheduler},
                    check_retry_fn=no_retry_4xx)
            except UsageError as e:
                raise(e)
            except Exception as e:
                # graphql schema exception is generic
                err = e
                continue
            err = None
            break
        if err:
            raise(err)

        sweep = response['upsertSweep']['sweep']
        project = sweep.get('project')
        if project:
            self.set_setting('project', project['name'])
            entity = project.get('entity')
            if entity:
                self.set_setting('entity', entity['name'])

        return response['upsertSweep']['sweep']['name']

    @normalize_exceptions
    def create_anonymous_api_key(self):
        """Creates a new API key belonging to a new anonymous user."""
        mutation = gql('''
        mutation CreateAnonymousApiKey {
            createAnonymousEntity(input: {}) {
                apiKey {
                    name
                }
            }
        }
        ''')

        response = self.gql(mutation, variable_values={})
        return response['createAnonymousEntity']['apiKey']['name']

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

    def get_project(self):
        return self.settings('project')

    @normalize_exceptions
    def push(self, files, run=None, entity=None, project=None, description=None, force=True, progress=False):
        """Uploads multiple files to W&B

        Args:
            files (list or dict): The filenames to upload
            run (str, optional): The run to upload to
            entity (str, optional): The entity to scope this project to.  Defaults to wandb models
            project (str, optional): The name of the project to upload to. Defaults to the one in settings.
            description (str, optional): The description of the changes
            force (bool, optional): Whether to prevent push if git has uncommitted changes
            progress (callable, or stream): If callable, will be called with (chunk_bytes,
                total_bytes) as argument else if True, renders a progress bar to stream.

        Returns:
            The requests library response object
        """
        if project is None:
            project = self.get_project()
        if project is None:
            raise CommError("No project configured.")
        if run is None:
            run = self.current_run_id

        # TODO(adrian): we use a retriable version of self.upload_file() so
        # will never retry self.upload_urls() here. Instead, maybe we should
        # make push itself retriable.
        run_id, upload_headers, result = self.upload_urls(
            project, files, run, entity, description)
        extra_headers = {}
        for upload_header in upload_headers:
            key, val = upload_header.split(':', 1)
            extra_headers[key] = val
        responses = []
        for file_name, file_info in result.items():
            file_url = file_info['url']

            # If the upload URL is relative, fill it in with the base URL,
            # since its a proxied file store like the on-prem VM.
            if file_url.startswith('/'):
                file_url = '{}{}'.format(self.api_url, file_url)

            try:
                # To handle Windows paths
                # TODO: this doesn't handle absolute paths...
                normal_name = os.path.join(*file_name.split("/"))
                open_file = files[file_name] if isinstance(
                    files, dict) else open(normal_name, "rb")
            except IOError:
                print("%s does not exist" % file_name)
                continue
            if progress:
                if hasattr(progress, '__call__'):
                    responses.append(self.upload_file_retry(
                        file_url, open_file, progress, extra_headers=extra_headers))
                else:
                    length = os.fstat(open_file.fileno()).st_size
                    with click.progressbar(file=progress, length=length, label='Uploading file: %s' % (file_name),
                                           fill_char=click.style('&', fg='green')) as bar:
                        responses.append(self.upload_file_retry(
                            file_url, open_file, lambda bites, _: bar.update(bites), extra_headers=extra_headers))
            else:
                responses.append(self.upload_file_retry(file_info['url'], open_file, extra_headers=extra_headers))
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
