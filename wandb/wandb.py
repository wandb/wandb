from gql import Client, gql
from gql.client import RetryError
from gql.transport.requests import RequestsHTTPTransport
import os, requests
from six.moves import configparser
from functools import wraps

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
    pass

def normalize_exceptions(func):
    """Function decorator for catching common errors and re-raising as wandb.Error"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except requests.HTTPError as err:
            raise Error(err)
        except RetryError as err:
            raise Error(err.last_exception)
    return wrapper

class Api(object):
    """W&B Api wrapper"""
    def __init__(self, default_config=None):
        """Initialize a new Api Client

        Note:
            Configuration parameters are automatically overriden by looking for
            a `.wandb` file in the current working directory or it's parent
            directories.  If none can be found, we look in the current users home
            directory.

        Args:
            default_config(:obj:`dict`, optional): If you aren't using config files
            or you wish to override the section to use in the config file.  Override
            the configuration variables here.
        """
        self.default_config = {
            'section': "default",
            'entity': "models",
            'base_url': "https://api.wandb.ai"
        }
        self.default_config.update(default_config or {})
        self.retries = 3
        self.config_parser = configparser.ConfigParser()
        self.config_file = self.config_parser.read([
            ".wandb", "../.wandb", "../../.wandb", os.path.expanduser('~/.wandb')
        ])
        self.client = Client(
            retries=self.retries,
            transport=RequestsHTTPTransport(
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
                    "model": None
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

    @normalize_exceptions
    def list_models(self, entity=None):
        """Lists models in W&B scoped by entity.
        
        Args:
            entity (str, optional): The entity to scope this model to.  Defaults to 
            public models

        Returns:
                [{"name","description"}]
        """
        query = gql('''
        query Models($entity: String!) {
            models(first: 10, entity: $entity) {
                edges {
                    node {
                        name: ndbId
                        description
                    }
                }
            }
        }
        ''')
        return self._flatten_edges(self.client.execute(query, variable_values={
            'entity': entity or self.config('entity')})['models'])

    @normalize_exceptions
    def create_revision(self, model, description=None, entity=None, part="patch"):
        """Create a new revision
        
        Args:
            model (str): The model to revise
            description (str, optional): A description of this revision
            part (str, optional): One of patch (default), minor or major specifying
            what part of the semantic version to bump
            entity (str, optional): The entity to scope this model to.  Defaults to 
            public models

        Returns:
            A revision dict with the upload urls

            {
                description
                version
                weightsUrl
                modelUrl
            }
        """
        mutation = gql('''
        mutation CreateRevision($id: String!, $entity: String!, $description: String, $part: String)  {
            createRevision(id: $id, entity: $entity, description: $description, which: $part) {
                revision {
                    description
                    version
                    weightsUrl(upload: true)
                    modelUrl(upload: true)
                }
            }
        }
        ''')
        response = self.client.execute(mutation, variable_values={
            'id':model, 'entity': entity or self.config('entity'),
            'description':description, 'part':part})
        return response['createRevision']['revision']

    @normalize_exceptions
    def upload_url(self, model, entity=None, kind="weightsUrl"):
        """Generate a temporary resumable upload url for a given file type
        
        Args:
            model (str): The model to download
            kind (str, optional): One of weightsUrl (default) or modelUrl
            entity (str, optional): The entity to scope this model to.  Defaults to 
            public models
        """
        query = gql('''
        query Model($id: String!, $entity: String!)  {
            model(id: $id, entity: $entity) {
                currentRevision {
                    weightsUrl(upload: true)
                    modelUrl(upload: true)
                }
            }
        }
        ''')
        urls = self.client.execute(query, variable_values={
            'id':model, 'entity': entity or self.config('entity')})
        return urls['model']['currentRevision'][kind]

    @normalize_exceptions
    def download_url(self, model, entity=None, kind="weightsUrl"):
        """Generate a download url for a given file type
        
        Args:
            model (str): The model to download
            kind (str, optional): One of weightsUrl (default) or modelUrl
            entity (str, optional): The entity to scope this model to.  Defaults to 
            public models

        Returns:
            A url to download that may require authentication.
        """
        query = gql('''
        query Model($id: String!, $entity: String!)  {
            model(id: $id, entity: $entity) {
                currentRevision {
                    weightsUrl
                    modelUrl
                }
            }
        }
        ''')
        urls = self.client.execute(query, variable_values={
            'id':model, 'entity': entity or self.config('entity')})
        return urls['model']['currentRevision'][kind]
    
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
                    print("Ran code %s" % extra_headers)
                else:
                    raise e
        return response

    def _status_request(self, url, length):
        """Ask google how much we've uploaded"""
        return requests.put(
            url=url,
            headers={'Content-Length': '0', 'Content-Range': 'bytes */%i' % length}
        )
    
    def _flatten_edges(self, response):
        """Return an array from the nested graphql relay structure"""
        return [node['node'] for node in response['edges']]
        