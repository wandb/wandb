import ast
import datetime
import json
import logging
import os
import re
import sys

# from wandb.git_repo import GitRepo
from gql import Client, gql  # type: ignore
from gql.client import RetryError  # type: ignore
from gql.transport.requests import RequestsHTTPTransport  # type: ignore
import requests
import six
from six import BytesIO
import wandb
from wandb import __version__, env, util
from wandb.apis.normalize import normalize_exceptions
from wandb.errors import CommError, UsageError
from wandb.old.settings import Settings
import yaml

PY3 = sys.version_info.major == 3 and sys.version_info.minor >= 6
if PY3:
    from wandb.sdk.lib import retry
else:
    from wandb.sdk_py27.lib import retry

logger = logging.getLogger(__name__)


class Api(object):
    """W&B Internal Api wrapper

    Note:
        Settings are automatically overridden by looking for
        a `wandb/settings` file in the current working directory or it's parent
        directory.  If none can be found, we look in the current users home
        directory.

    Arguments:
        default_settings(`dict`, optional): If you aren't using a settings
        file or you wish to override the section to use in the settings file
        Override the settings here.
    """

    HTTP_TIMEOUT = env.get_http_timeout(10)

    def __init__(
        self,
        default_settings=None,
        load_settings=True,
        retry_timedelta=None,
        environ=os.environ,
    ):
        if retry_timedelta is None:
            retry_timedelta = datetime.timedelta(days=1)
        self._environ = environ
        self.default_settings = {
            "section": "default",
            "git_remote": "origin",
            "ignore_globs": [],
            "base_url": "https://api.wandb.ai",
        }
        self.retry_timedelta = retry_timedelta
        self.default_settings.update(default_settings or {})
        self.retry_uploads = 10
        self._settings = Settings(
            load_settings=load_settings, root_dir=self.default_settings.get("root_dir")
        )
        # self.git = GitRepo(remote=self.settings("git_remote"))
        self.git = None
        # Mutable settings set by the _file_stream_api
        self.dynamic_settings = {
            "system_sample_seconds": 2,
            "system_samples": 15,
            "heartbeat_seconds": 30,
        }
        self.client = Client(
            transport=RequestsHTTPTransport(
                headers={
                    "User-Agent": self.user_agent,
                    "X-WANDB-USERNAME": env.get_username(env=self._environ),
                    "X-WANDB-USER-EMAIL": env.get_user_email(env=self._environ),
                },
                use_json=True,
                # this timeout won't apply when the DNS lookup fails. in that case, it will be 60s
                # https://bugs.python.org/issue22889
                timeout=self.HTTP_TIMEOUT,
                auth=("api", self.api_key or ""),
                url="%s/graphql" % self.settings("base_url"),
            )
        )
        self.gql = retry.Retry(
            self.execute,
            retry_timedelta=retry_timedelta,
            check_retry_fn=util.no_retry_auth,
            retryable_exceptions=(RetryError, requests.RequestException),
        )
        self._current_run_id = None
        self._file_stream_api = None

    def reauth(self):
        """Ensures the current api key is set in the transport"""
        self.client.transport.auth = ("api", self.api_key or "")

    def relocate(self):
        """Ensures the current api points to the right server"""
        self.client.transport.url = "%s/graphql" % self.settings("base_url")

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

        if "errors" in data and isinstance(data["errors"], list):
            for err in data["errors"]:
                if not err.get("message"):
                    continue
                wandb.termerror(
                    "Error while calling W&B API: {} ({})".format(err["message"], res)
                )

    def disabled(self):
        return self._settings.get(Settings.DEFAULT_SECTION, "disabled", fallback=False)

    def set_current_run_id(self, run_id):
        self._current_run_id = run_id

    @property
    def current_run_id(self):
        return self._current_run_id

    @property
    def user_agent(self):
        return "W&B Internal Client %s" % __version__

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
        return self.settings("base_url")

    @property
    def app_url(self):
        return wandb.util.app_url(self.api_url)

    def settings(self, key=None, section=None):
        """The settings overridden from the wandb/settings file.

        Arguments:
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
        result.update(
            {
                "entity": env.get_entity(
                    self._settings.get(
                        Settings.DEFAULT_SECTION,
                        "entity",
                        fallback=result.get("entity"),
                    ),
                    env=self._environ,
                ),
                "project": env.get_project(
                    self._settings.get(
                        Settings.DEFAULT_SECTION,
                        "project",
                        fallback=result.get("project"),
                    ),
                    env=self._environ,
                ),
                "base_url": env.get_base_url(
                    self._settings.get(
                        Settings.DEFAULT_SECTION,
                        "base_url",
                        fallback=result.get("base_url"),
                    ),
                    env=self._environ,
                ),
                "ignore_globs": env.get_ignore(
                    self._settings.get(
                        Settings.DEFAULT_SECTION,
                        "ignore_globs",
                        fallback=result.get("ignore_globs"),
                    ),
                    env=self._environ,
                ),
            }
        )

        return result if key is None else result[key]

    def clear_setting(self, key, globally=False, persist=False):
        self._settings.clear(
            Settings.DEFAULT_SECTION, key, globally=globally, persist=persist
        )

    def set_setting(self, key, value, globally=False, persist=False):
        self._settings.set(
            Settings.DEFAULT_SECTION, key, value, globally=globally, persist=persist
        )
        if key == "entity":
            env.set_entity(value, env=self._environ)
        elif key == "project":
            env.set_project(value, env=self._environ)
        elif key == "base_url":
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
        query = gql(
            """
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
        """
        )
        res = self.gql(query)
        return res.get("viewer") or {}

    @normalize_exceptions
    def list_projects(self, entity=None):
        """Lists projects in W&B scoped by entity.

        Arguments:
            entity (str, optional): The entity to scope this project to.

        Returns:
                [{"id","name","description"}]
        """
        query = gql(
            """
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
        """
        )
        return self._flatten_edges(
            self.gql(
                query, variable_values={"entity": entity or self.settings("entity")}
            )["models"]
        )

    @normalize_exceptions
    def project(self, project, entity=None):
        """Retrive project

        Arguments:
            project (str): The project to get details for
            entity (str, optional): The entity to scope this project to.

        Returns:
                [{"id","name","repo","dockerImage","description"}]
        """
        query = gql(
            """
        query Models($entity: String, $project: String!) {
            model(name: $project, entityName: $entity) {
                id
                name
                repo
                dockerImage
                description
            }
        }
        """
        )
        return self.gql(query, variable_values={"entity": entity, "project": project})[
            "model"
        ]

    @normalize_exceptions
    def sweep(self, sweep, specs, project=None, entity=None):
        """Retrieve sweep.

        Arguments:
            sweep (str): The sweep to get details for
            specs (str): history specs
            project (str, optional): The project to scope this sweep to.
            entity (str, optional): The entity to scope this sweep to.

        Returns:
                [{"id","name","repo","dockerImage","description"}]
        """
        query = gql(
            """
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
        """
        )
        entity = entity or self.settings("entity")
        project = project or self.settings("project")
        response = self.gql(
            query,
            variable_values={
                "entity": entity,
                "project": project,
                "sweep": sweep,
                "specs": specs,
            },
        )
        if response["model"] is None or response["model"]["sweep"] is None:
            raise ValueError("Sweep {}/{}/{} not found".format(entity, project, sweep))
        data = response["model"]["sweep"]
        if data:
            data["runs"] = self._flatten_edges(data["runs"])
        return data

    @normalize_exceptions
    def list_runs(self, project, entity=None):
        """Lists runs in W&B scoped by project.

        Arguments:
            project (str): The project to scope the runs to
            entity (str, optional): The entity to scope this project to.  Defaults to public models

        Returns:
                [{"id",name","description"}]
        """
        query = gql(
            """
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
        """
        )
        return self._flatten_edges(
            self.gql(
                query,
                variable_values={
                    "entity": entity or self.settings("entity"),
                    "model": project or self.settings("project"),
                },
            )["model"]["buckets"]
        )

    @normalize_exceptions
    def launch_run(self, command, project=None, entity=None, run_id=None):
        """Launch a run in the cloud.

        Arguments:
            command (str): The command to run
            program (str): The file to run
            project (str): The project to scope the runs to
            entity (str, optional): The entity to scope this project to.  Defaults to public models
            run_id (str, optional): The run_id to scope to

        Returns:
                [{"podName","status"}]
        """
        query = gql(
            """
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
        """
        )
        run_id = run_id or self.current_run_id
        assert run_id, "run_id must be specified"
        patch = BytesIO()
        if self.git.dirty:
            self.git.repo.git.execute(["git", "diff"], output_stream=patch)
            patch.seek(0)
        cwd = "."
        if self.git.enabled:
            cwd = cwd + os.getcwd().replace(self.git.repo.working_dir, "")
        return self.gql(
            query,
            variable_values={
                "entity": entity or self.settings("entity"),
                "model": project or self.settings("project"),
                "command": command,
                "runId": run_id,
                "patch": patch.read().decode("utf8"),
                "cwd": cwd,
            },
        )

    @normalize_exceptions
    def run_config(self, project, run=None, entity=None):
        """Get the relevant configs for a run

        Arguments:
            project (str): The project to download, (can include bucket)
            run (str): The run to download
            entity (str, optional): The entity to scope this project to.
        """
        query = gql(
            """
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
        """
        )
        run = run or self.current_run_id
        assert run, "run must be specified"
        response = self.gql(
            query, variable_values={"name": project, "run": run, "entity": entity}
        )
        if response["model"] is None:
            raise ValueError("Run {}/{}/{} not found".format(entity, project, run))
        run = response["model"]["bucket"]
        commit = run["commit"]
        patch = run["patch"]
        config = json.loads(run["config"] or "{}")
        if len(run["files"]["edges"]) > 0:
            url = run["files"]["edges"][0]["node"]["url"]
            res = requests.get(url)
            res.raise_for_status()
            metadata = res.json()
        else:
            metadata = {}
        return (commit, config, patch, metadata)

    @normalize_exceptions
    def run_resume_status(self, entity, project_name, name):
        """Check if a run exists and get resume information.

        Arguments:
            entity (str, optional): The entity to scope this project to.
            project_name (str): The project to download, (can include bucket)
            name (str): The run to download
        """
        query = gql(
            """
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
        """
        )

        response = self.gql(
            query,
            variable_values={"entity": entity, "project": project_name, "name": name,},
        )

        if "model" not in response or "bucket" not in (response["model"] or {}):
            return None

        project = response["model"]
        self.set_setting("project", project_name)
        if "entity" in project:
            self.set_setting("entity", project["entity"]["name"])

        return project["bucket"]

    @normalize_exceptions
    def check_stop_requested(self, project_name, entity_name, run_id):
        query = gql(
            """
        query Model($projectName: String, $entityName: String, $runId: String!) {
            project(name:$projectName, entityName:$entityName) {
                run(name:$runId) {
                    stopped
                }
            }
        }
        """
        )
        run_id = run_id or self.current_run_id
        assert run_id, "run_id must be specified"
        response = self.gql(
            query,
            variable_values={
                "projectName": project_name,
                "entityName": entity_name,
                "runId": run_id,
            },
        )

        project = response.get("project", None)
        if not project:
            return False
        run = project.get("run", None)
        if not run:
            return False

        return run["stopped"]

    def format_project(self, project):
        return re.sub(r"\W+", "-", project.lower()).strip("-_")

    @normalize_exceptions
    def upsert_project(self, project, id=None, description=None, entity=None):
        """Create a new project

        Arguments:
            project (str): The project to create
            description (str, optional): A description of this project
            entity (str, optional): The entity to scope this project to.
        """
        mutation = gql(
            """
        mutation UpsertModel($name: String!, $id: String, $entity: String!, $description: String, $repo: String)  {
            upsertModel(input: { id: $id, name: $name, entityName: $entity, description: $description, repo: $repo }) {
                model {
                    name
                    description
                }
            }
        }
        """
        )
        response = self.gql(
            mutation,
            variable_values={
                "name": self.format_project(project),
                "entity": entity or self.settings("entity"),
                "description": description,
                "repo": self.git.remote_url,
                "id": id,
            },
        )
        return response["upsertModel"]["model"]

    @normalize_exceptions
    def pop_from_run_queue(self, entity=None, project=None):
        mutation = gql(
            """
        mutation popFromRunQueue($entity: String!, $project: String!)  {
            popFromRunQueue(input: { entityName: $entity, projectName: $project }) {
                runQueueItemId
                runSpec
            }
        }
        """
        )
        response = self.gql(
            mutation, variable_values={"entity": entity, "project": project}
        )
        return response["popFromRunQueue"]

    @normalize_exceptions
    def upsert_run(
        self,
        id=None,
        name=None,
        project=None,
        host=None,
        group=None,
        tags=None,
        config=None,
        description=None,
        entity=None,
        state=None,
        display_name=None,
        notes=None,
        repo=None,
        job_type=None,
        program_path=None,
        commit=None,
        sweep_name=None,
        summary_metrics=None,
        num_retries=None,
    ):
        """Update a run

        Arguments:
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
        mutation = gql(
            """
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
        """
        )
        if config is not None:
            config = json.dumps(config)
        if not description or description.isspace():
            description = None

        kwargs = {}
        if num_retries is not None:
            kwargs["num_retries"] = num_retries

        variable_values = {
            "id": id,
            "entity": entity or self.settings("entity"),
            "name": name,
            "project": project,
            "groupName": group,
            "tags": tags,
            "description": description,
            "config": config,
            "commit": commit,
            "displayName": display_name,
            "notes": notes,
            "host": None if self.settings().get("anonymous") == "true" else host,
            "debug": env.is_debug(env=self._environ),
            "repo": repo,
            "program": program_path,
            "jobType": job_type,
            "state": state,
            "sweep": sweep_name,
            "summaryMetrics": summary_metrics,
        }

        response = self.gql(mutation, variable_values=variable_values, **kwargs)

        run = response["upsertBucket"]["bucket"]
        project = run.get("project")
        if project:
            self.set_setting("project", project["name"])
            entity = project.get("entity")
            if entity:
                self.set_setting("entity", entity["name"])

        return response["upsertBucket"]["bucket"]

    @normalize_exceptions
    def upload_urls(self, project, files, run=None, entity=None, description=None):
        """Generate temporary resumeable upload urls

        Arguments:
            project (str): The project to download
            files (list or dict): The filenames to upload
            run (str): The run to upload to
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
        query = gql(
            """
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
        """
        )
        run_id = run or self.current_run_id
        assert run, "run must be specified"
        entity = entity or self.settings("entity")
        query_result = self.gql(
            query,
            variable_values={
                "name": project,
                "run": run_id,
                "entity": entity,
                "description": description,
                "files": [file for file in files],
            },
        )

        run = query_result["model"]["bucket"]
        if run:
            result = {file["name"]: file for file in self._flatten_edges(run["files"])}
            return run["id"], run["files"]["uploadHeaders"], result
        else:
            raise CommError(
                "Run does not exist {}/{}/{}.".format(entity, project, run_id)
            )

    @normalize_exceptions
    def download_urls(self, project, run=None, entity=None):
        """Generate download urls

        Arguments:
            project (str): The project to download
            run (str): The run to upload to
            entity (str, optional): The entity to scope this project to.  Defaults to wandb models

        Returns:
            A dict of extensions and urls

                {
                    'weights.h5': { "url": "https://weights.url", "updatedAt": '2013-04-26T22:22:23.832Z', 'md5': 'mZFLkyvTelC5g8XnyQrpOw==' },
                    'model.json': { "url": "https://model.url", "updatedAt": '2013-04-26T22:22:23.832Z', 'md5': 'mZFLkyvTelC5g8XnyQrpOw==' }
                }
        """
        query = gql(
            """
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
        """
        )
        run = run or self.current_run_id
        assert run, "run must be specified"
        query_result = self.gql(
            query,
            variable_values={
                "name": project,
                "run": run,
                "entity": entity or self.settings("entity"),
            },
        )
        files = self._flatten_edges(query_result["model"]["bucket"]["files"])
        return {file["name"]: file for file in files if file}

    @normalize_exceptions
    def download_url(self, project, file_name, run=None, entity=None):
        """Generate download urls

        Arguments:
            project (str): The project to download
            file_name (str): The name of the file to download
            run (str): The run to upload to
            entity (str, optional): The entity to scope this project to.  Defaults to wandb models

        Returns:
            A dict of extensions and urls

                { "url": "https://weights.url", "updatedAt": '2013-04-26T22:22:23.832Z', 'md5': 'mZFLkyvTelC5g8XnyQrpOw==' }

        """
        query = gql(
            """
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
        """
        )
        run = run or self.current_run_id
        assert run, "run must be specified"
        query_result = self.gql(
            query,
            variable_values={
                "name": project,
                "run": run,
                "fileName": file_name,
                "entity": entity or self.settings("entity"),
            },
        )
        if query_result["model"]:
            files = self._flatten_edges(query_result["model"]["bucket"]["files"])
            return files[0] if len(files) > 0 and files[0].get("updatedAt") else None
        else:
            return None

    @normalize_exceptions
    def download_file(self, url):
        """Initiate a streaming download

        Arguments:
            url (str): The url to download

        Returns:
            A tuple of the content length and the streaming response
        """
        response = requests.get(url, stream=True)
        response.raise_for_status()
        return (int(response.headers.get("content-length", 0)), response)

    @normalize_exceptions
    def download_write_file(self, metadata, out_dir=None):
        """Download a file from a run and write it to wandb/

        Arguments:
            metadata (obj): The metadata object for the file to download. Comes from Api.download_urls().

        Returns:
            A tuple of the file's local path and the streaming response. The streaming response is None if the file already existed and was up to date.
        """
        file_name = metadata["name"]
        path = os.path.join(out_dir or self.settings("wandb_dir"), file_name)
        if self.file_current(file_name, metadata["md5"]):
            return path, None

        size, response = self.download_file(metadata["url"])

        with util.fsync_open(path, "wb") as file:
            for data in response.iter_content(chunk_size=1024):
                file.write(data)

        return path, response

    @normalize_exceptions
    def register_agent(self, host, sweep_id=None, project_name=None, entity=None):
        """Register a new agent

        Arguments:
            host (str): hostname
            persistent (bool): long running or oneoff
            sweep (str): sweep id
            project_name: (str): model that contains sweep
        """
        mutation = gql(
            """
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
        """
        )
        if entity is None:
            entity = self.settings("entity")
        if project_name is None:
            project_name = self.settings("project")

        # don't retry on validation or not found errors
        def no_retry_4xx(e):
            if not isinstance(e, requests.HTTPError):
                return True
            if not (e.response.status_code >= 400 and e.response.status_code < 500):
                return True
            body = json.loads(e.response.content)
            raise UsageError(body["errors"][0]["message"])

        response = self.gql(
            mutation,
            variable_values={
                "host": host,
                "entityName": entity,
                "projectName": project_name,
                "sweep": sweep_id,
            },
            check_retry_fn=no_retry_4xx,
        )
        return response["createAgent"]["agent"]

    def agent_heartbeat(self, agent_id, metrics, run_states):
        """Notify server about agent state, receive commands.

        Arguments:
            agent_id (str): agent_id
            metrics (dict): system metrics
            run_states (dict): run_id: state mapping
        Returns:
            List of commands to execute.
        """
        mutation = gql(
            """
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
        """
        )
        try:
            response = self.gql(
                mutation,
                variable_values={
                    "id": agent_id,
                    "metrics": json.dumps(metrics),
                    "runState": json.dumps(run_states),
                },
            )
        except Exception as e:
            # GQL raises exceptions with stringified python dictionaries :/
            message = ast.literal_eval(e.args[0])["message"]
            logger.error("Error communicating with W&B: %s", message)
            return []
        else:
            return json.loads(response["agentHeartbeat"]["commands"])

    @normalize_exceptions
    def upsert_sweep(
        self,
        config,
        controller=None,
        scheduler=None,
        obj_id=None,
        project=None,
        entity=None,
    ):
        """Upsert a sweep object.

        Arguments:
            config (str): sweep config (will be converted to yaml)
        """
        project_query = """
                    project {
                        id
                        name
                        entity {
                            id
                            name
                        }
                    }
        """
        mutation_str = """
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
        """
        # TODO(jhr): we need protocol versioning to know schema is not supported
        # for now we will just try both new and old query
        mutation_new = gql(mutation_str.replace("_PROJECT_QUERY_", project_query))
        mutation_old = gql(mutation_str.replace("_PROJECT_QUERY_", ""))

        # don't retry on validation errors
        # TODO(jhr): generalize error handling routines
        def no_retry_4xx(e):
            if not isinstance(e, requests.HTTPError):
                return True
            if not (e.response.status_code >= 400 and e.response.status_code < 500):
                return True
            body = json.loads(e.response.content)
            raise UsageError(body["errors"][0]["message"])

        for mutation in mutation_new, mutation_old:
            try:
                response = self.gql(
                    mutation,
                    variable_values={
                        "id": obj_id,
                        "config": yaml.dump(config),
                        "description": config.get("description"),
                        "entityName": entity or self.settings("entity"),
                        "projectName": project or self.settings("project"),
                        "controller": controller,
                        "scheduler": scheduler,
                    },
                    check_retry_fn=no_retry_4xx,
                )
            except UsageError as e:
                raise (e)
            except Exception as e:
                # graphql schema exception is generic
                err = e
                continue
            err = None
            break
        if err:
            raise (err)

        sweep = response["upsertSweep"]["sweep"]
        project = sweep.get("project")
        if project:
            self.set_setting("project", project["name"])
            entity = project.get("entity")
            if entity:
                self.set_setting("entity", entity["name"])

        return response["upsertSweep"]["sweep"]["name"]

    @normalize_exceptions
    def create_anonymous_api_key(self):
        """Creates a new API key belonging to a new anonymous user."""
        mutation = gql(
            """
        mutation CreateAnonymousApiKey {
            createAnonymousEntity(input: {}) {
                apiKey {
                    name
                }
            }
        }
        """
        )

        response = self.gql(mutation, variable_values={})
        return response["createAnonymousEntity"]["apiKey"]["name"]

    def file_current(self, fname, md5):
        """Checksum a file and compare the md5 with the known md5"""
        return os.path.isfile(fname) and util.md5_file(fname) == md5

    @normalize_exceptions
    def pull(self, project, run=None, entity=None):
        """Download files from W&B

        Arguments:
            project (str): The project to download
            run (str): The run to upload to
            entity (str, optional): The entity to scope this project to.  Defaults to wandb models

        Returns:
            The requests library response object
        """
        project, run = self.parse_slug(project, run=run)
        assert run, "run must be specified"
        urls = self.download_urls(project, run, entity)
        responses = []
        for file_name in urls:
            _, response = self.download_write_file(urls[file_name])
            if response:
                responses.append(response)

        return responses

    def get_project(self):
        return self.settings("project")

    def _status_request(self, url, length):
        """Ask google how much we've uploaded"""
        return requests.put(
            url=url,
            headers={"Content-Length": "0", "Content-Range": "bytes */%i" % length},
        )

    def _flatten_edges(self, response):
        """Return an array from the nested graphql relay structure"""
        return [node["node"] for node in response["edges"]]
