import logging
import requests
import time
import sys
import os
import json
import re
import six
import tempfile
import datetime
from gql import Client, gql
from gql.client import RetryError
from gql.transport.requests import RequestsHTTPTransport
from six.moves import urllib

import wandb
from wandb import Error, __version__
from wandb import util
from wandb.retry import retriable
from wandb.summary import HTTPSummary, download_h5
from wandb.env import get_dir
from wandb.env import get_base_url
from wandb.apis import normalize_exceptions

logger = logging.getLogger(__name__)

RUN_FRAGMENT = '''fragment RunFragment on Run {
    id
    tags
    name
    displayName
    state
    config
    readOnly
    createdAt
    heartbeatAt
    description
    notes
    systemMetrics
    summaryMetrics
    user {
        name
        username
    }
}'''

FILE_FRAGMENT = '''fragment RunFilesFragment on Run {
    files(names: $fileNames, after: $fileCursor, first: $fileLimit) {
        edges {
            node {
                id
                name
                url(upload: $upload)
                sizeBytes
                mimetype
                updatedAt
                md5
            }
            cursor
        }
        pageInfo {
            endCursor
            hasNextPage
        }
    }
}'''


class RetryingClient(object):
    def __init__(self, client):
        self._client = client

    @retriable(retry_timedelta=datetime.timedelta(
        seconds=20),
        check_retry_fn=util.no_retry_auth,
        retryable_exceptions=(RetryError, requests.RequestException))
    def execute(self, *args, **kwargs):
        return self._client.execute(*args, **kwargs)


class Api(object):
    """W&B Public API

    Args:
        setting_overrides(:obj:`dict`, optional): You can set defaults such as
        username, project, and run here as well as which api server to use.
    """

    HTTP_TIMEOUT = 9

    def __init__(self, overrides={}):
        self.settings = {
            'username': None,
            'project': None,
            'run': "latest",
            'base_url': get_base_url("https://api.wandb.ai")
        }
        self._runs = {}
        self._base_client = Client(
            transport=RequestsHTTPTransport(
                headers={'User-Agent': self.user_agent},
                use_json=True,
                # this timeout won't apply when the DNS lookup fails. in that case, it will be 60s
                # https://bugs.python.org/issue22889
                timeout=self.HTTP_TIMEOUT,
                auth=("api", self.api_key),
                url='%s/graphql' % self.settings['base_url']
            )
        )
        self._client = RetryingClient(self._base_client)
        self.settings.update(overrides)

    def create_run(self, **kwargs):
        return Run.create(self, **kwargs)

    @property
    def client(self):
        return self._client

    @property
    def user_agent(self):
        return 'W&B Public Client %s' % __version__

    @property
    def api_key(self):
        auth = requests.utils.get_netrc_auth(self.settings['base_url'])
        key = None
        if auth:
            key = auth[-1]
        # Environment should take precedence
        if os.getenv("WANDB_API_KEY"):
            key = os.environ["WANDB_API_KEY"]
        return key

    def flush(self):
        """Clear the local cache"""
        self._runs = {}

    def _parse_path(self, path):
        """Parses paths in the following formats:

        url: username/project/runs/run_id
        path: username/project/run_id
        docker: username/project:run_id

        username is optional and will fallback to the current logged in user.
        """
        run = self.settings['run']
        project = self.settings['project']
        username = self.settings['username']
        parts = path.replace("/runs/", "/").split("/")
        if ":" in parts[-1]:
            run = parts[-1].split(":")[-1]
            parts[-1] = parts[-1].split(":")[0]
        elif parts[-1]:
            run = parts[-1]
        if len(parts) > 1:
            project = parts[1]
            if username and run == project:
                project = parts[0]
            else:
                username = parts[0]
        else:
            project = parts[0]
        return (username, project, run)

    def runs(self, path="", filters={}, order="-created_at", per_page=None):
        """Return a set of runs from a project that match the filters provided.
        You can filter by config.*, summary.*, state, username, createdAt, etc.

        The filters use the same query language as MongoDB:

        https://docs.mongodb.com/manual/reference/operator/query

        Order can be created_at, heartbeat_at, config.*.value, or summary.*.  By default
        the order is descending, if you prepend order with a + order becomes ascending.
        """
        username, project, run = self._parse_path(path)
        if not self._runs.get(path):
            self._runs[path + str(filters) + str(order)] = Runs(self.client, username, project,
                                                                filters=filters, order=order, per_page=per_page)
        return self._runs[path + str(filters) + str(order)]

    @normalize_exceptions
    def run(self, path=""):
        """Returns a run by parsing path in the form username/project/run, if
        defaults were set on the Api, only overrides what's passed.  I.E. you can just pass
        run_id if you set username and project on the Api"""
        username, project, run = self._parse_path(path)
        if not self._runs.get(path):
            self._runs[path] = Run(self.client, username, project, run)
        return self._runs[path]


class Attrs(object):
    def __init__(self, attrs):
        self._attrs = attrs

    def snake_to_camel(self, string):
        camel = "".join([i.title() for i in string.split("_")])
        return camel[0].lower() + camel[1:]

    def __getattr__(self, name):
        key = self.snake_to_camel(name)
        if key == "user":
            raise AttributeError()
        if key in self._attrs.keys():
            return self._attrs[key]
        elif name in self._attrs.keys():
            return self._attrs[name]
        else:
            raise AttributeError(
                "'{}' object has no attribute '{}'".format(self.__repr__, name))


class Paginator(object):
    QUERY = None

    def __init__(self, client, variables, per_page=50):
        self.client = client
        self.variables = variables
        self.per_page = per_page
        self.objects = []
        self.index = -1
        self.last_response = None

    def __iter__(self):
        self.index = -1
        return self

    def __len__(self):
        if self.length is None:
            self._load_page()
        return self.length

    @property
    def length(self):
        raise NotImplementedError()

    @property
    def more(self):
        raise NotImplementedError()

    @property
    def cursor(self):
        raise NotImplementedError()

    def convert_objects(self):
        raise NotImplementedError()

    def update_variables(self):
        self.variables.update(
            {'perPage': self.per_page, 'cursor': self.cursor})

    def _load_page(self):
        if not self.more:
            return False

        self.update_variables()
        self.last_response = self.client.execute(
            self.QUERY, variable_values=self.variables)
        self.objects.extend(self.convert_objects())
        return True

    def __getitem__(self, index):
        loaded = True
        while loaded and index > len(self.objects) - 1:
            loaded = self._load_page()
        return self.objects[index]

    def __next__(self):
        self.index += 1
        if len(self.objects) <= self.index:
            if not self._load_page():
                raise StopIteration
        return self.objects[self.index]

    next = __next__


class User(Attrs):
    def init(self, attrs):
        super(User, self).__init__(attrs)


class Runs(Paginator):
    QUERY = gql('''
        query Runs($project: String!, $entity: String!, $cursor: String, $perPage: Int = 50, $order: String, $filters: JSONString) {
            project(name: $project, entityName: $entity) {
                runCount(filters: $filters)
                readOnly
                runs(filters: $filters, after: $cursor, first: $perPage, order: $order) {
                    edges {
                        node {
                            ...RunFragment
                        }
                        cursor
                    }
                    pageInfo {
                        endCursor
                        hasNextPage
                    }
                }
            }
        }
        %s
        ''' % RUN_FRAGMENT)

    def __init__(self, client, username, project, filters={}, order=None, per_page=50):
        self.username = username
        self.project = project
        self.filters = filters
        self.order = order
        variables = {
            'project': self.project, 'entity': self.username, 'order': self.order,
            'filters': json.dumps(self.filters)
        }
        super(Runs, self).__init__(client, variables, per_page)

    @property
    def length(self):
        if self.last_response:
            return self.last_response['project']['runCount']
        else:
            return None

    @property
    def more(self):
        if self.last_response:
            return self.last_response['project']['runs']['pageInfo']['hasNextPage']
        else:
            return True

    @property
    def cursor(self):
        if self.last_response:
            return self.last_response['project']['runs']['edges'][-1]['cursor']
        else:
            return None

    def convert_objects(self):
        return [Run(self.client, self.username, self.project, r["node"]["name"], r["node"])
                for r in self.last_response['project']['runs']['edges']]

    def __repr__(self):
        return "<Runs {}/{} ({})>".format(self.username, self.project, len(self))


class Run(Attrs):
    """A single run associated with a user and project"""

    def __init__(self, client, username, project, name, attrs={}):
        self.client = client
        self.username = username
        self.project = project
        self.name = name
        self._files = {}
        self._base_dir = get_dir(tempfile.gettempdir())
        self.dir = os.path.join(self._base_dir, *self.path)
        try:
            os.makedirs(self.dir)
        except OSError:
            pass
        self._summary = None
        super(Run, self).__init__(attrs)
        self.state = attrs.get("state", "not found")
        self.load()

    @property
    def storage_id(self):
        """For compatibility with wandb.Run, which has storage IDs
        in self.storage_id and names in self.id, whereas this has storage IDs in
        self.id and names in self.id
        """
        return self.id

    @classmethod
    def create(cls, api, run_id=None, project=None, username=None):
        """Create a run for the given project"""
        run_id = run_id or util.generate_id()
        project = project or api.settings.get("project")
        mutation = gql('''
        mutation upsertRun($project: String, $entity: String, $name: String!) {
            upsertBucket(input: {modelName: $project, entityName: $entity, name: $name}) {
                bucket {
                    project {
                        name
                        entity { name }
                    }
                    id
                    name
                }
                inserted
            }
        }
        ''')
        variables = {'entity': username,
                     'project': project, 'name': run_id}
        res = api.client.execute(mutation, variable_values=variables)
        res = res['upsertBucket']['bucket']
        return Run(api.client, res["project"]["entity"]["name"],  res["project"]["name"], res["name"], {
            "id": res["id"],
            "config": "{}",
            "systemMetrics": "{}",
            "summaryMetrics": "{}",
            "tags": [],
            "description": None,
            "notes": None,
            "state": "running"
        })

    def load(self, force=False):
        query = gql('''
        query Run($project: String!, $entity: String!, $name: String!) {
            project(name: $project, entityName: $entity) {
                run(name: $name) {
                    ...RunFragment
                }
            }
        }
        %s
        ''' % RUN_FRAGMENT)
        if force or not self._attrs:
            response = self._exec(query)
            if response['project'] is None or response['project']['run'] is None:
                raise ValueError("Could not find run %s" % self)
            self._attrs = response['project']['run']
            self.state = self._attrs['state']
        self._attrs['summaryMetrics'] = json.loads(
            self._attrs['summaryMetrics']) if self._attrs.get('summaryMetrics') else {}
        self._attrs['systemMetrics'] = json.loads(
            self._attrs['systemMetrics']) if self._attrs.get('systemMetrics') else {}
        if self._attrs.get('user'):
            self.user = User(self._attrs["user"])
        config = {}
        for key, value in six.iteritems(json.loads(self._attrs.get('config') or "{}")):
            if isinstance(value, dict) and value.get("value"):
                config[key] = value["value"]
            else:
                config[key] = value
        self._attrs['config'] = config
        return self._attrs

    @normalize_exceptions
    def update(self):
        mutation = gql('''
        mutation upsertRun($id: String!, $description: String, $display_name: String, $notes: String, $tags: [String!], $config: JSONString!) {
            upsertBucket(input: {id: $id, description: $description, displayName: $display_name, notes: $notes, tags: $tags, config: $config}) {
                bucket {
                    ...RunFragment
                }
            }
        }
        %s
        ''' % RUN_FRAGMENT)
        res = self._exec(mutation, id=self.id, tags=self.tags,
                         description=self.description, notes=self.notes, display_name=self.display_name, config=self.json_config)
        self.summary.update()

    @property
    def json_config(self):
        config = {}
        for k, v in six.iteritems(self.config):
            config[k] = {"value": v, "desc": None}
        return json.dumps(config)

    def _exec(self, query, **kwargs):
        """Execute a query against the cloud backend"""
        variables = {'entity': self.username,
                     'project': self.project, 'name': self.name}
        variables.update(kwargs)
        return self.client.execute(query, variable_values=variables)

    @normalize_exceptions
    def files(self, names=[], per_page=50):
        return Files(self.client, self, names, per_page)

    @normalize_exceptions
    def file(self, name):
        return Files(self.client, self, [name])[0]

    @normalize_exceptions
    def history(self, samples=500, pandas=True, stream="default"):
        """Return history metrics for a run

        Args:
            samples (int, optional): The number of samples to return
            pandas (bool, optional): Return a pandas dataframe
            stream (str, optional): "default" for metrics, "system" for machine metrics
        """
        node = "history" if stream == "default" else "events"
        query = gql('''
        query Run($project: String!, $entity: String!, $name: String!, $samples: Int!) {
            project(name: $project, entityName: $entity) {
                run(name: $name) { %s(samples: $samples) }
            }
        }
        ''' % node)

        response = self._exec(query, samples=samples)
        lines = [json.loads(line)
                 for line in response['project']['run'][node]]
        if pandas:
            pandas = util.get_module("pandas")
            if pandas:
                lines = pandas.DataFrame.from_records(lines)
            else:
                print("Unable to load pandas, call history with pandas=False")
        return lines

    @property
    def summary(self):
        if self._summary is None:
            download_h5(self.name, entity=self.username,
                        project=self.project, out_dir=self.dir)
            # TODO: fix the outdir issue
            self._summary = HTTPSummary(
                self, self.client, summary=self.summary_metrics)
        return self._summary

    @property
    def path(self):
        return [urllib.parse.quote_plus(str(self.username)), urllib.parse.quote_plus(str(self.project)), urllib.parse.quote_plus(str(self.name))]

    @property
    def url(self):
        path = self.path
        path.insert(2, "runs")
        return "https://app.wandb.ai/" + "/".join(path)

    def __repr__(self):
        return "<Run {} ({})>".format("/".join(self.path), self.state)


class Files(Paginator):
    QUERY = gql('''
        query Run($project: String!, $entity: String!, $name: String!, $fileCursor: String,
            $fileLimit: Int = 50, $fileNames: [String] = [], $upload: Boolean = false) {
            project(name: $project, entityName: $entity) {
                run(name: $name) {
                    fileCount
                    ...RunFilesFragment
                }
            }
        }
        %s
        ''' % FILE_FRAGMENT)

    def __init__(self, client, run, names=[], per_page=50, upload=False):
        self.run = run
        variables = {
            'project': run.project, 'entity': run.username, 'name': run.name,
            'fileNames': names, 'upload': upload
        }
        super(Files, self).__init__(client, variables, per_page)

    @property
    def length(self):
        if self.last_response:
            return self.last_response['project']['run']['fileCount']
        else:
            return None

    @property
    def more(self):
        if self.last_response:
            return self.last_response['project']['run']['files']['pageInfo']['hasNextPage']
        else:
            return True

    @property
    def cursor(self):
        if self.last_response:
            return self.last_response['project']['run']['files']['edges'][-1]['cursor']
        else:
            return None

    def update_variables(self):
        self.variables.update({'fileLimit': self.per_page, 'fileCursor': self.cursor})

    def convert_objects(self):
        return [File(self.client, r["node"])
                for r in self.last_response['project']['run']['files']['edges']]

    def __repr__(self):
        return "<Files {} ({})>".format("/".join(self.run.path), len(self))


class File(object):
    def __init__(self, client, attrs):
        self.client = client
        self._attrs = attrs
        if self.size == 0:
            raise AttributeError(
                "File {} does not exist.".format(self._attrs["name"]))

    @property
    def name(self):
        return self._attrs["name"]

    @property
    def url(self):
        return self._attrs["url"]

    @property
    def md5(self):
        return self._attrs["md5"]

    @property
    def mimetype(self):
        return self._attrs["mimetype"]

    @property
    def updated_at(self):
        return self._attrs["updatedAt"]

    @property
    def size(self):
        return int(self._attrs["sizeBytes"])

    @normalize_exceptions
    @retriable(retry_timedelta=datetime.timedelta(
        seconds=10),
        check_retry_fn=util.no_retry_auth,
        retryable_exceptions=(RetryError, requests.RequestException))
    def download(self, replace=False, root="."):
        response = requests.get(self._attrs["url"], auth=(
            "api", Api().api_key), stream=True, timeout=5)
        response.raise_for_status()
        path = os.path.join(root, self._attrs["name"])
        if os.path.exists(path) and not replace:
            raise ValueError(
                "File already exists, pass replace=True to overwrite")
        if "/" in path:
            dir = "/".join(path.split("/")[0:-1])
            util.mkdir_exists_ok(dir)
        with open(path, "wb") as file:
            for data in response.iter_content(chunk_size=1024):
                file.write(data)
        return open(path, "r")

    def __repr__(self):
        return "<File {} ({})>".format(self.name, self.mimetype)
