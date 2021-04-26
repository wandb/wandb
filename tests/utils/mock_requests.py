import json
import threading
import requests


class ResponseMock(object):
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def raise_for_status(self):
        # convert flask Response to requests Response
        response = requests.Response()
        response.status_code = self.response.status_code
        if self.response.status_code == 429:
            response._content = b'{"error": "rate limit exceeded"}'
            raise requests.exceptions.HTTPError(response=response)
        elif self.response.status_code >= 400:
            response._content = b"Bad Request"
            raise requests.exceptions.HTTPError(response=response)

    @property
    def status_code(self):
        return self.response.status_code

    @property
    def content(self):
        return self.response.data

    @property
    def text(self):
        return self.response.data.decode("utf-8")

    @property
    def headers(self):
        return self.response.headers

    def iter_content(self, chunk_size=1024):
        yield self.response.data

    def json(self):
        str_data = self.response.data.decode("utf-8")
        return json.loads(str_data) if str_data else {}


class RequestsMock(object):
    def __init__(self, app, ctx):
        self.app = app
        self.client = app.test_client()
        self.ctx = ctx
        self._lock = threading.Lock()

    def set_context(self, key, value):
        with self._lock:
            self.ctx[key] = value

    def Session(self):
        return self

    @property
    def RequestException(self):
        return requests.RequestException

    @property
    def HTTPError(self):
        return requests.HTTPError

    @property
    def headers(self):
        return {}

    @property
    def __version__(self):
        return requests.__version__

    @property
    def utils(self):
        return requests.utils

    @property
    def exceptions(self):
        return requests.exceptions

    @property
    def packages(self):
        return requests.packages

    @property
    def adapters(self):
        return requests.adapters

    def mount(self, *args):
        pass

    def _clean_kwargs(self, kwargs):
        if "auth" in kwargs:
            del kwargs["auth"]
        if "timeout" in kwargs:
            del kwargs["timeout"]
        if "cookies" in kwargs:
            del kwargs["cookies"]
        if "params" in kwargs:
            del kwargs["params"]
        if "stream" in kwargs:
            del kwargs["stream"]
        if "verify" in kwargs:
            del kwargs["verify"]
        if "allow_redirects" in kwargs:
            del kwargs["allow_redirects"]
        return kwargs

    def _store_request(self, url, body):
        parts = url.split("?")
        key = parts[0].split("/")[-1]
        if len(parts) > 1:
            # To make assertions easier, we remove the run from storage requests
            key = key + "?" + parts[1].split("&run=")[0]
        with self._lock:
            self.ctx[key] = self.ctx.get(key, [])
            self.ctx[key].append(body)

    def post(self, url, **kwargs):
        self._store_request(url, kwargs.get("json"))
        return ResponseMock(self.client.post(url, **self._clean_kwargs(kwargs)))

    def put(self, url, **kwargs):
        self._store_request(url, kwargs.get("json"))
        return ResponseMock(self.client.put(url, **self._clean_kwargs(kwargs)))

    def get(self, url, **kwargs):
        self._store_request(url, kwargs.get("json"))
        return ResponseMock(self.client.get(url, **self._clean_kwargs(kwargs)))

    def request(self, method, url, **kwargs):
        if method.lower() == "get":
            self.get(url, **kwargs)
        elif method.lower() == "post":
            self.post(url, **kwargs)
        elif method.lower() == "put":
            self.put(url, **kwargs)
        else:
            message = "Request method not implemented: %s" % method
            raise requests.RequestException(message)

    def __repr__(self):
        return "<W&B Mocked Request class>"
