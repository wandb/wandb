from gql import Client, gql
from gql.client import RetryError
from gql.transport.requests import RequestsHTTPTransport
import os, requests, ast
from six.moves import configparser
from functools import wraps
import logging, hashlib, os
from wandb import __version__
from base64 import b64encode

def IDENTITY(monitor):
    """A default callback for the Progress helper"""
    return monitor

class Progress(object):
    """A helper class for displaying progress"""
    def __init__(self, file, callback=None):
        self.file = file
        self.callback = callback or IDENTITY
        self.bytes_read = 0
        self.len = os.fstat(file.fileno()).st_size

    def read(self, size=-1):
        """Read bytes and call the callback"""
        bites = self.file.read(size)
        self.bytes_read += len(bites)
        self.callback(len(bites))
        return bites

class Error(Exception):
    """An error communicating with W&B"""
    #For python 2 support
    def encode(self, encoding):
        return self.message

def normalize_exceptions(func):
    """Function decorator for catching common errors and re-raising as wandb.Error"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except requests.HTTPError as err:
            raise Error(err.response)
        except RetryError as err:
            if "response" in dir(err.last_exception) and err.last_exception.response is not None:
                message = err.last_exception.response.json().get('errors', [{'message': 'Whoa, you found a bug.'}])[0]['message']
            else:
                message = err.last_exception
            raise Error(message)
        except Exception as err:
            try:
                # gql raises server errors with dict's as strings...
                message = ast.literal_eval(err.args[0]).get("message", "Server Error")
            except SyntaxError as e:
                logging.error(err)
                message = "Whoa, you found a bug."
            raise Error(message)
    return wrapper

class Api(object):
    """W&B Api wrapper"""
    def __init__(self, default_config=None, load_config=True):
        """Initialize a new Api Client

        Note:
            Configuration parameters are automatically overriden by looking for
            a `.wandb` file in the current working directory or it's parent
            directory.  If none can be found, we look in the current users home
            directory.

        Args:
            default_config(:obj:`dict`, optional): If you aren't using config files
            or you wish to override the section to use in the config file.  Override
            the configuration variables here.
        """
        self.default_config = {
            'section': "default",
            'entity': "models",
            'bucket': "default",
            'base_url': "https://api.wandb.ai"
        }
        self.default_config.update(default_config or {})
        self.retries = 3
        self.config_parser = configparser.ConfigParser()
        if load_config:
            self.config_file = self.config_parser.read([
                os.path.expanduser('~/.wandb'), os.getcwd() + "/../.wandb", os.getcwd() + "/.wandb"
            ])
        else:
            self.config_file = []
        self.client = Client(
            retries=self.retries,
            transport=RequestsHTTPTransport(
                headers={'User-Agent': 'W&B Client %s' % __version__},
                use_json=True,
                url='%s/graphql' % self.config('base_url')
            )
        )

    def config(self, key=None, section=None):
        """The configuration overriden from the .wandb file.

        Args:
            key (str, optional): If provided only this config param is returned
            section (str, optional): If provided this section of the config file is
            used, defaults to "default"

        Returns:
            A dict with the current config

                {
                    "entity": "models",
                    "base_url": "https://api.wandb.ai",
                    "project": None
                }
        """
        config = self.default_config.copy()
        section = section or config['section']
        try:
            if section in self.config_parser.sections():
                for option in self.config_parser.options(section):
                    config[option] = self.config_parser.get(section, option)
        except configparser.InterpolationSyntaxError:
            print("WARNING: Unable to parse config file")
            pass
        return config if key is None else config[key]

    def parse_slug(self, slug, project=None, bucket=None):
        if "/" in slug:
            parts = slug.split("/")
            project = parts[0]
            bucket = parts[1]
        else:
            project = project or self.config().get("project")
            if project is None:
                raise Error("No default project configured.")
            bucket = bucket or slug
        return (project, bucket)

    @normalize_exceptions
    def viewer(self):
        query = gql('''
        query Viewer{
            viewer {
                id
                entity
            }
        }
        ''')
        return self.client.execute(query).get('viewer', {})

    @normalize_exceptions
    def list_projects(self, entity=None):
        """Lists projects in W&B scoped by entity.
        
        Args:
            entity (str, optional): The entity to scope this project to.  Defaults to public models

        Returns:
                [{"name","description"}]
        """
        query = gql('''
        query Models($entity: String!) {
            models(first: 10, entityName: $entity) {
                edges {
                    node {
                        name
                        description
                    }
                }
            }
        }
        ''')
        return self._flatten_edges(self.client.execute(query, variable_values={
            'entity': entity or self.config('entity')})['models'])

    @normalize_exceptions
    def list_buckets(self, project, entity=None):
        """Lists buckets in W&B scoped by project.
        
        Args:
            project (str): The project to scope the tags to
            entity (str, optional): The entity to scope this project to.  Defaults to public models

        Returns:
                [{"name","description"}]
        """
        query = gql('''
        query Buckets($model: String!, $entity: String!) {
            model(name: $model, entityName: $entity) {
                buckets(first: 10) {
                    edges {
                        node {
                            name
                            description
                        }
                    }
                }
            }
        }
        ''')
        return self._flatten_edges(self.client.execute(query, variable_values={
            'entity': entity or self.config('entity'), 
            'model': project or self.config('project')})['model']['buckets'])

    @normalize_exceptions
    def create_project(self, project, description=None, entity=None):
        """Create a new project
        
        Args:
            project (str): The project to create
            description (str, optional): A description of this project
            entity (str, optional): The entity to scope this project to.
        """
        mutation = gql('''
        mutation UpsertModel($name: String!, $entity: String!, $description: String)  {
            upsertModel(input: { name: $name, entityName: $entity, description: $description }) {
                model {
                    name
                    description
                }
            }
        }
        ''')
        response = self.client.execute(mutation, variable_values={
            'name':project, 'entity': entity or self.config('entity'),
            'description':description})
        return response['upsertModel']['model']

    @normalize_exceptions
    def upload_urls(self, project, files, bucket=None, entity=None, description=None):
        """Generate temporary resumable upload urls
        
        Args:
            project (str): The project to download
            bucket (str, optional): The bucket to upload to
            entity (str, optional): The entity to scope this project to.  Defaults to wandb models

        Returns:
            A dict of filenames and urls, also indicates if this revision already has uploaded files

                {
                    'weights.h5': { "url": "https://weights.url" }, 
                    'model.json': { "url": "https://model.json", "updatedAt": '2013-04-26T22:22:23.832Z' }
                }
        """
        query = gql('''
        query Model($name: String!, $files: [String]!, $entity: String!, $bucket: String!, $description: String) {
            model(name: $name, entityName: $entity) {
                bucket(name: $bucket, desc: $description) {
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
        query_result = self.client.execute(query, variable_values={
            'name':project, 'bucket': bucket or self.config('bucket'), 
            'entity': entity or self.config('entity'),
            'description': description,
            'files': [file for file in files]
        })
        bucket = query_result['model']['bucket']
        result = {file['name']: file for file in self._flatten_edges(bucket['files'])}

        return result

    @normalize_exceptions
    def download_urls(self, project, bucket=None, entity=None):
        """Generate download urls
        
        Args:
            project (str): The project to download
            bucket (str, optional): The bucket to upload to
            entity (str, optional): The entity to scope this project to.  Defaults to wandb models

        Returns:
            A dict of extensions and urls

                {
                    'weights.h5': { "url": "https://weights.url", "updatedAt": '2013-04-26T22:22:23.832Z' }, 
                    'model.json': { "url": "https://model.url", "updatedAt": '2013-04-26T22:22:23.832Z' }
                }
        """
        query = gql('''
        query Model($name: String!, $entity: String!, $bucket: String!)  {
            model(name: $name, entityName: $entity) {
                bucket(name: $bucket) {
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
        query_result = self.client.execute(query, variable_values={
            'name':project, 'bucket': bucket or self.config('bucket'), 'entity': entity or self.config('entity')})
        files = self._flatten_edges(query_result['model']['bucket']['files'])
        return {file['name']: file for file in files}
    
    @normalize_exceptions
    def download_file(self, url):
        """Initiate a streaming download

        Args:
            url (str): The url to download

        Returns:
            A tupil of the content length and the streaming response
        """
        response = requests.get(url, stream=True)
        response.raise_for_status()
        return (int(response.headers.get('content-length', 0)), response)

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
            raise Error("%s is an empty file" % file.name)
        while attempts < self.retries:
            try:
                progress = Progress(file, callback=callback)
                response = requests.put(url, data=progress, headers=extra_headers)
                response.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                total = progress.len
                status = self._status_request(url, total)
                if(status.status_code == 308):
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

    def _md5(self, fname):
        hash_md5 = hashlib.md5()
        with open(fname, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return b64encode(hash_md5.digest()).decode('ascii')

    def file_current(self, fname, md5):
        """Checksum a file and compare the md5 with the known md5
        """
        return os.path.isfile(fname) and self._md5(fname) == md5

    @normalize_exceptions
    def pull(self, project, bucket=None, entity=None, description=None):
        """Download files from W&B
        
        Args:
            project (str): The project to download
            bucket (str, optional): The bucket to upload to
            entity (str, optional): The entity to scope this project to.  Defaults to wandb models

        Returns:
            The requests library response object
        """
        project, bucket = self.parse_slug(project, bucket=bucket)
        urls = self.download_urls(project, bucket, entity)
        responses = []
        for fileName in urls:
            if self.file_current(fileName, urls[fileName]['md5']):
                continue
            with open(fileName, "wb") as file:
                size, res = self.download_file(urls[fileName]['url'])
                responses.append(res)
                for data in res.iter_content():
                    file.write(data)
        return responses

    @normalize_exceptions
    def push(self, project, files, bucket=None, entity=None, description=None):
        """Uploads multiple files to W&B
        
        Args:
            project (str): The project to download
            files (list or dict): The filenames to upload
            bucket (str, optional): The bucket to upload to
            entity (str, optional): The entity to scope this project to.  Defaults to wandb models

        Returns:
            The requests library response object
        """
        project, bucket = self.parse_slug(project, bucket=bucket)
        urls = self.upload_urls(project, files, bucket, entity, description)
        responses = []
        for fileName in urls:
            file = files[fileName] if type(files) == dict else open(fileName, "rb")
            responses.append(self.upload_file(urls[fileName]['url'], file))
            file.close()
        return responses

    def _status_request(self, url, length):
        """Ask google how much we've uploaded"""
        return requests.put(
            url=url,
            headers={'Content-Length': '0', 'Content-Range': 'bytes */%i' % length}
        )
    
    def _flatten_edges(self, response):
        """Return an array from the nested graphql relay structure"""
        return [node['node'] for node in response['edges']]
        