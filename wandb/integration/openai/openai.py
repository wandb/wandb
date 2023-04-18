import logging
import socket
import threading
import urllib.parse
from typing import Dict, List, Mapping, Optional

import requests

import wandb.util
from wandb.testing.relay import RawRequestResponse, Timer

flask = wandb.util.get_module(
    name="flask",
    required="To use the W&B OpenAI Autolog, you need to have the `flask` python "
    "package installed. Please install it with `pip install flask`.",
    lazy=False,
)

openai = wandb.util.get_module(
    name="openai",
    required="To use the W&B OpenAI Autolog, you need to have the `openai` python "
    "package installed. Please install it with `pip install openai`.",
    lazy=False,
)


class Relay:
    def __init__(self) -> None:
        self.app = flask.Flask(__name__)
        self.app.logger.setLevel(logging.INFO)
        # disable flask's default message:
        flask.cli.show_server_banner = lambda *args: None

        self.app.add_url_rule(
            rule="/<path:subpath>",
            endpoint="snoopy",
            view_func=self.snoopy,
            methods=["GET", "POST"],
        )

        self.port = self._get_free_port()
        # self.base_url = openai.api_base
        self.base_url = urllib.parse.urlparse(openai.api_base)
        print(self.base_url)
        self.session = requests.Session()
        self.relay_url = f"http://127.0.0.1:{self.port}/{self.base_url.path}"

        self._relay_server_thread: Optional[threading.Thread] = None

        self.context: List[Dict[str, str]] = []

        # useful for debugging:
        # self.after_request_fn = self.app.after_request(self.after_request_fn)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop()

    @staticmethod
    def _get_free_port() -> int:
        sock = socket.socket()
        sock.bind(("", 0))

        _, port = sock.getsockname()
        return port

    def start(self) -> None:
        if self._relay_server_thread is not None:
            return
        # run server in a separate thread
        self._relay_server_thread = threading.Thread(
            target=self.app.run,
            kwargs={"port": self.port},
            daemon=True,
        )
        self._relay_server_thread.start()
        openai.api_base = self.relay_url

    def stop(self) -> None:
        if self._relay_server_thread is None:
            return
        # self._relay_server_thread.join()
        self._relay_server_thread = None
        openai.api_base = self.base_url.geturl()
        # openai.api_base = str(self.base_url)

    def after_request_fn(self, response: "requests.Response") -> "requests.Response":
        # todo: this is useful for debugging, but should be removed in the future
        # flask.request.url = self.relay_url + flask.request.url
        print(flask.request)
        print(flask.request.get_json())
        print(response)
        print(response.json())
        return response

    def relay(
        self,
        request: "flask.Request",
    ) -> "requests.Response":
        # replace the relay url with the real backend url (self.base_url)
        url = (
            urllib.parse.urlparse(request.url)
            ._replace(netloc=self.base_url.netloc, scheme=self.base_url.scheme)
            .geturl()
        )
        headers = {key: value for (key, value) in request.headers if key != "Host"}
        prepared_relayed_request = requests.Request(
            method=request.method,
            url=url,
            headers=headers,
            data=request.get_data(),
            json=request.get_json(),
        ).prepare()

        relayed_response = self.session.send(prepared_relayed_request)
        return relayed_response

    def save(
        self,
        request: "flask.Request",
        response: "requests.Response",
        time_elapsed: float,
    ) -> None:
        request_data = request.get_json()
        response_data = response.json() or {}

        # store raw data
        raw_data: "RawRequestResponse" = {
            "url": request.url,
            "request": request_data,
            "response": response_data,
            "time_elapsed": time_elapsed,
        }
        self.context.append(raw_data)

        # todo: add context resolvers
        # todo: save parsed context to wandb
        #  if parsing fails, just save the raw data !!

    def snoopy(self, subpath) -> Mapping[str, str]:
        request = flask.request
        with Timer() as timer:
            relayed_response = self.relay(request)
        print("*****************")
        print("REQUEST:")
        print(request.get_json())
        print("RESPONSE:")
        print(relayed_response.status_code, relayed_response.json())
        print("*****************")
        # snoop work to extract the context
        self.save(request, relayed_response, timer.elapsed)

        return relayed_response.json()


class Autolog:
    def __init__(
        self,
        project: Optional[str] = None,
        entity: Optional[str] = None,
    ):
        # autolog = Autolog()
        # autolog.enable()
        # # doo da ding...he don't miss!!!
        # autolog.disable()
        pass

    # do the same thing as the context manager
    def enable(self):
        pass

    def disable(self):
        pass
