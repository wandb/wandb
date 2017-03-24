from gql import Client, gql
from gql.transport.requests import RequestsHTTPTransport
import requests
import os

def IDENTITY(monitor):
    return monitor

class Progress(object):
    def __init__(self, file, callback=None):
        self.file = file
        self.callback = callback or IDENTITY
        self.bytes_read = 0
        self.len = os.fstat(file.fileno()).st_size

    def read(self, size=-1):
        bites = self.file.read(size)
        self.bytes_read += len(bites)
        self.callback(len(bites))
        return bites

BASE_URL= "http://localhost:5000" if os.getenv('DEBUG') else "https://api.wandb.ai" 
class Api(object):
    """W&B Api wrapper"""
    def __init__(self):
        self.retries = 3
        self.client = Client(
            retries=self.retries,
            transport=RequestsHTTPTransport(
                use_json=True,
                url='%s/graphql' % BASE_URL
            )
        )

    def list_models(self):
        """Lists models in W&B"""
        query = gql('''
        query Models {
            models(first: 10, entity: "models") {
                edges {
                    node {
                        ndbId
                        description
                    }
                }
            }
        }
        ''')
        return self.client.execute(query)

    def upload_url(self, model, kind="weightsUrl"):
        query = gql('''
        query Model($id: String!)  {
            model(id: $id) {
                weightsUrl(upload: true)
                modelUrl(upload: true)
            }
        }
        ''')
        urls = self.client.execute(query, variable_values={'id':model})
        return urls['model'][kind]

    def download_url(self, model, kind="weightsUrl"):
        query = gql('''
        query Model($id: String!)  {
            model(id: $id) {
                weightsUrl
                modelUrl
            }
        }
        ''')
        urls = self.client.execute(query, variable_values={'id':model})
        return urls['model'][kind]

    def download_file(self, url):
        response = requests.get(url, stream=True)
        response.raise_for_status()
        return (int(response.headers.get('content-length')), response)

    def upload_file(self, url, file, callback):
        """Creates a model in W&B"""
        self.attempts = 0
        extra_headers = {}
        while(self.attempts < self.retries):
            try:
                progress = Progress(file, callback=callback)
                response = requests.put(url, data=progress, headers=extra_headers)
                break
            except requests.exceptions.RequestException as e:
                total = progress.len
                status = self.status_request(total)
                if(status.status_code == 308):
                    self.attempts += 1
                    completed = int(status.headers['Range'].split("-")[-1])
                    extra_headers = {
                        'Content-Range': 'bytes {completed}-{total}/{total}'.format(
                            completed=completed, 
                            total=total
                        ),
                        'Content-Length': total - completed
                    }
                else:
                    break
        return response

    def status_request(self, length):
        return requests.put(
            url=self.upload_url,
            headers={'Content-Length': 0, 'Content-Range': 'bytes */%i' % length}
        )
        