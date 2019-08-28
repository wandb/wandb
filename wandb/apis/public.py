import logging
import requests
import time
import sys
import os
import json
import re
import six
import yaml
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
from wandb.summary import HTTPSummary
from wandb import env
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
    historyLineCount
    user {
        name
        username
    }
    historyKeys
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
        entity, project, and run here as well as which api server to use.
    """

    HTTP_TIMEOUT = env.get_http_timeout(9)

    def __init__(self, overrides={}):
        self.settings = {
            'entity': None,
            'project': None,
            'run': "latest",
            'base_url': env.get_base_url("https://api.wandb.ai")
        }
        self.settings.update(overrides)
        if 'username' in overrides and 'entity' not in overrides:
            wandb.termwarn('Passing "username" to Api is deprecated. please use "entity" instead.')
            self.settings['entity'] = overrides['username']
        self._runs = {}
        self._sweeps = {}
        self._base_client = Client(
            transport=RequestsHTTPTransport(
                headers={'User-Agent': self.user_agent, 'Use-Admin-Privileges': "true"},
                use_json=True,
                # this timeout won't apply when the DNS lookup fails. in that case, it will be 60s
                # https://bugs.python.org/issue22889
                timeout=self.HTTP_TIMEOUT,
                auth=("api", self.api_key),
                url='%s/graphql' % self.settings['base_url']
            )
        )
        self._client = RetryingClient(self._base_client)

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

        url: entity/project/runs/run_id
        path: entity/project/run_id
        docker: entity/project:run_id

        entity is optional and will fallback to the current logged in user.
        """
        run = self.settings['run']
        project = self.settings['project']
        entity = self.settings['entity']
        parts = path.replace("/runs/", "/").strip("/ ").split("/")
        if ":" in parts[-1]:
            run = parts[-1].split(":")[-1]
            parts[-1] = parts[-1].split(":")[0]
        elif parts[-1]:
            run = parts[-1]
        if len(parts) > 1:
            project = parts[1]
            if entity and run == project:
                project = parts[0]
            else:
                entity = parts[0]
        else:
            project = parts[0]
        return (entity, project, run)

    def runs(self, path="", filters={}, order="-created_at", per_page=None):
        """Return a set of runs from a project that match the filters provided.
        You can filter by config.*, summary.*, state, entity, createdAt, etc.

        The filters use the same query language as MongoDB:

        https://docs.mongodb.com/manual/reference/operator/query

        Order can be created_at, heartbeat_at, config.*.value, or summary.*.  By default
        the order is descending, if you prepend order with a + order becomes ascending.
        """
        entity, project, run = self._parse_path(path)
        if not self._runs.get(path):
            self._runs[path + str(filters) + str(order)] = Runs(self.client, entity, project,
                                                                filters=filters, order=order, per_page=per_page)
        return self._runs[path + str(filters) + str(order)]

    @normalize_exceptions
    def run(self, path=""):
        """Returns a run by parsing path in the form entity/project/run, if
        defaults were set on the Api, only overrides what's passed.  I.E. you can just pass
        run_id if you set entity and project on the Api"""
        entity, project, run = self._parse_path(path)
        if not self._runs.get(path):
            self._runs[path] = Run(self.client, entity, project, run)
        return self._runs[path]

    @normalize_exceptions
    def sweep(self, path=""):
        entity, project, sweep_id = self._parse_path(path)
        if not self._sweeps.get(sweep_id):
            self._sweeps[path] = Sweep(self.client, entity, project, sweep_id)
        return self._sweeps[path]


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
                "'{}' object has no attribute '{}'".format(repr(self), name))


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

    def __init__(self, client, entity, project, filters={}, order=None, per_page=50):
        self.entity = entity
        self.project = project
        self.filters = filters
        self.order = order
        variables = {
            'project': self.project, 'entity': self.entity, 'order': self.order,
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
        return [Run(self.client, self.entity, self.project, r["node"]["name"], r["node"])
                for r in self.last_response['project']['runs']['edges']]

    def __repr__(self):
        return "<Runs {}/{} ({})>".format(self.entity, self.project, len(self))


class Run(Attrs):
    """A single run associated with a user and project"""

    def __init__(self, client, entity, project, run_id, attrs={}):
        super(Run, self).__init__(dict(attrs))
        self.client = client
        self._entity = entity
        self.project = project
        self._files = {}
        self._base_dir = env.get_dir(tempfile.gettempdir())
        self.id = run_id
        self.dir = os.path.join(self._base_dir, *self.path)
        try:
            os.makedirs(self.dir)
        except OSError:
            pass
        self._summary = None
        self.state = attrs.get("state", "not found")

        self.load(force=not attrs)

    @property
    def entity(self):
        return self._entity

    @property
    def username(self):
        wandb.termwarn('Run.username is deprecated. Please use Run.entity instead.')
        return self._entity

    @property
    def storage_id(self):
        """For compatibility with wandb.Run, which has storage IDs
        in self.storage_id and names in self.id.
        """
        return self._attrs.get('id')

    @property
    def id(self):
        return self._attrs.get('name')

    @id.setter
    def id(self, new_id):
        attrs = self._attrs
        attrs['name'] = new_id
        return new_id

    @property
    def name(self):
        return self._attrs.get('displayName')

    @name.setter
    def name(self, new_name):
        self._attrs['displayName'] = new_name
        return new_name

    @classmethod
    def create(cls, api, run_id=None, project=None, entity=None):
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
        variables = {'entity': entity,
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
        res = self._exec(mutation, id=self.storage_id, tags=self.tags,
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
        variables = {'entity': self.entity,
                     'project': self.project, 'name': self.id}
        variables.update(kwargs)
        return self.client.execute(query, variable_values=variables)

    def _sampled_history(self, keys, x_axis="_step", samples=500):
        spec = {"keys": [x_axis] + keys, "samples": samples}
        query = gql('''
        query Run($project: String!, $entity: String!, $name: String!, $specs: [JSONString!]!) {
            project(name: $project, entityName: $entity) {
                run(name: $name) { sampledHistory(specs: $specs) }
            }
        }
        ''')

        response = self._exec(query, specs=[json.dumps(spec)])
        return [line for line in response['project']['run']['sampledHistory']]


    def _full_history(self, samples=500, stream="default"):
        node = "history" if stream == "default" else "events"
        query = gql('''
        query Run($project: String!, $entity: String!, $name: String!, $samples: Int) {
            project(name: $project, entityName: $entity) {
                run(name: $name) { %s(samples: $samples) }
            }
        }
        ''' % node)

        response = self._exec(query, samples=samples)
        return [json.loads(line) for line in response['project']['run'][node]]

    @normalize_exceptions
    def files(self, names=[], per_page=50):
        return Files(self.client, self, names, per_page)

    @normalize_exceptions
    def file(self, name):
        return Files(self.client, self, [name])[0]

    @normalize_exceptions
    def history(self, samples=500, keys=None, x_axis="_step", pandas=True, stream="default"):
        """Return history metrics for a run

        Args:
            samples (int, optional): The number of samples to return
            pandas (bool, optional): Return a pandas dataframe
            keys (list, optional): Only return metrics for specific keys
            x_axis (str, optional): Use this metric as the xAxis defaults to _step
            stream (str, optional): "default" for metrics, "system" for machine metrics
        """
        if keys and stream != "default":
            wandb.termerror("stream must be default when specifying keys")
            return []
        elif keys:
            lines = self._sampled_history(keys=keys, x_axis=x_axis, samples=samples)
        else:
            lines = self._full_history(samples=samples, stream=stream)
        if pandas:
            pandas = util.get_module("pandas")
            if pandas:
                lines = pandas.DataFrame.from_records(lines)
            else:
                print("Unable to load pandas, call history with pandas=False")
        return lines

    @normalize_exceptions
    def scan_history(self, keys=None, page_size=1000):
        """Returns an iterable that returns all history for a run unsampled

        Args:
            keys ([str], optional): only fetch these keys, and rows that have all of them
            page_size (int, optional): size of pages to fetch from the api
        """
        if keys is None:
            return HistoryScan(run=self, client=self.client, page_size=page_size)
        else:
            return SampledHistoryScan(run=self, client=self.client, keys=keys, page_size=page_size)

    @property
    def summary(self):
        if self._summary is None:
            # TODO: fix the outdir issue
            self._summary = HTTPSummary(
                self, self.client, summary=self.summary_metrics)
        return self._summary

    @property
    def path(self):
        return [urllib.parse.quote_plus(str(self.entity)), urllib.parse.quote_plus(str(self.project)), urllib.parse.quote_plus(str(self.id))]

    @property
    def url(self):
        path = self.path
        path.insert(2, "runs")
        return "https://app.wandb.ai/" + "/".join(path)

    @property
    def lastHistoryStep(self):
        history_keys = self._attrs['historyKeys']
        return history_keys['lastStep'] if 'lastStep' in history_keys else -1

    def __repr__(self):
        return "<Run {} ({})>".format("/".join(self.path), self.state)

class Sweep(Attrs):
    """A set of runs associated with a sweep"""

    def __init__(self, client, entity, project, sweep_id, attrs={}):
        # TODO: Add agents / flesh this out.
        super(Sweep, self).__init__(dict(attrs))
        self.client = client
        self._entity = entity
        self.project = project
        self.id = sweep_id
        self.runs = []

        self.load(force=not attrs)

    @property
    def entity(self):
        return self._entity

    @property
    def username(self):
        wandb.termwarn('Sweep.username is deprecated. please use Sweep.entity instead.')
        return self._entity

    @property
    def config(self):
        return yaml.load(self._attrs["config"])

    def load(self, force=False):
        query = gql('''
        query Sweep($project: String!, $entity: String, $name: String!) {
            project(name: $project, entityName: $entity) {
                sweep(sweepName: $name) {
                    id
                    name
                    bestLoss
                    config
                    runs {
                        edges {
                            node {
                                ...RunFragment
                            }
                        }
                    }
                }
            }
        }
        %s
        ''' % RUN_FRAGMENT)
        if force or not self._attrs:
            response = self._exec(query)
            if response['project'] is None or response['project']['sweep'] is None:
                raise ValueError("Could not find sweep %s" % self)
            # TODO: make this paginate
            self.runs = [Run(self.client, self.entity, self.project, r["node"]["name"], r["node"]) for
                r in response['project']['sweep']['runs']['edges']]
            del response['project']['sweep']['runs']
            self._attrs = response['project']['sweep']
        return self._attrs

    @property
    def path(self):
        return [urllib.parse.quote_plus(str(self.entity)), urllib.parse.quote_plus(str(self.project)), urllib.parse.quote_plus(str(self.id))]

    def _exec(self, query, **kwargs):
        """Execute a query against the cloud backend"""
        variables = {'entity': self.entity,
                     'project': self.project, 'name': self.id}
        variables.update(kwargs)
        return self.client.execute(query, variable_values=variables)

    def __repr__(self):
        return "<Sweep {}>".format("/".join(self.path))


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
            'project': run.project, 'entity': run.entity, 'name': run.id,
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

class HistoryScan(object):
    QUERY = gql('''
        query HistoryPage($entity: String!, $project: String!, $run: String!, $minStep: Int64!, $maxStep: Int64!, $pageSize: Int!) {
            project(name: $project, entityName: $entity) {
                run(name: $run) {
                    history(minStep: $minStep, maxStep: $maxStep, samples: $pageSize)
                }
            }
        }
        ''')

    def __init__(self, client, run, page_size=1000):
        self.client = client
        self.run = run
        self.page_size = page_size
        self.page_offset = 0 # minStep for next page
        self.scan_offset = 0 # index within current page of rows
        self.rows = [] # current page of rows

    def __iter__(self):
        self.page_offset = 0
        self.scan_offset = 0
        self.rows = []
        return self

    def __next__(self):
        while True:
            if self.scan_offset < len(self.rows):
                row = self.rows[self.scan_offset]
                self.scan_offset += 1
                return row
            if self.page_offset > self.run.lastHistoryStep:
                raise StopIteration()
            self._load_next()

    @normalize_exceptions
    @retriable(
        check_retry_fn=util.no_retry_auth,
        retryable_exceptions=(RetryError, requests.RequestException))
    def _load_next(self):
        variables = {
            "entity": self.run.entity,
            "project": self.run.project,
            "run": self.run.id,
            "minStep": int(self.page_offset),
            "maxStep": int(self.page_offset + self.page_size),
            "pageSize": int(self.page_size)
        }

        res = self.client.execute(self.QUERY, variable_values=variables)
        res = res['project']['run']['history']
        self.rows = [json.loads(row) for row in res]
        self.page_offset += self.page_size
        self.scan_offset = 0

class SampledHistoryScan(object):
    QUERY = gql('''
        query SampledHistoryPage($entity: String!, $project: String!, $run: String!, $spec: JSONString!) {
            project(name: $project, entityName: $entity) {
                run(name: $run) {
                    sampledHistory(specs: [$spec])
                }
            }
        }
        ''')

    def __init__(self, client, run, keys, page_size=1000):
        self.client = client
        self.run = run
        self.keys = keys
        self.page_size = page_size
        self.page_offset = 0 # minStep for next page
        self.scan_offset = 0 # index within current page of rows
        self.rows = [] # current page of rows

    def __iter__(self):
        self.page_offset = 0
        self.scan_offset = 0
        self.rows = []
        return self

    def __next__(self):
        while True:
            if self.scan_offset < len(self.rows):
                row = self.rows[self.scan_offset]
                self.scan_offset += 1
                return row
            if self.page_offset >= self.run.lastHistoryStep:
                raise StopIteration()
            self._load_next()

    @normalize_exceptions
    @retriable(
        check_retry_fn=util.no_retry_auth,
        retryable_exceptions=(RetryError, requests.RequestException))
    def _load_next(self):
        variables = {
            "entity": self.run.entity,
            "project": self.run.project,
            "run": self.run.id,
            "spec": json.dumps({
                "keys": self.keys,
                "minStep": int(self.page_offset),
                "maxStep": int(self.page_offset + self.page_size),
                "samples": int(self.page_size)
            })
        }

        res = self.client.execute(self.QUERY, variable_values=variables)
        res = res['project']['run']['sampledHistory']
        self.rows = res[0]
        self.page_offset += self.page_size
        self.scan_offset = 0
