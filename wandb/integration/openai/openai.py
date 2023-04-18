import logging
import socket
import sys
import threading
import urllib.parse
from typing import Any, Dict, List, Mapping, Optional, TypeVar

import requests

import wandb.util
from wandb.sdk.data_types import trace_tree
from wandb.testing.relay import RawRequestResponse, Timer

if sys.version_info >= (3, 8):
    from typing import Literal, Protocol
else:
    from typing_extensions import Literal, Protocol

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


K = TypeVar("K", bound=str)
V = TypeVar("V")


class OpenAIResponse(Protocol[K, V]):
    # contains a (known) object attribute
    object: Literal["chat.completion", "edit", "text_completion"]

    def __getitem__(self, key: K) -> V:
        ...  # pragma: no cover

    def __setitem__(self, key: K, value: V) -> None:
        ...  # pragma: no cover

    def __delitem__(self, key: K) -> None:
        ...  # pragma: no cover

    def __iter__(self) -> Any:
        ...  # pragma: no cover

    def __len__(self) -> int:
        ...  # pragma: no cover

    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        ...  # pragma: no cover


class OpenAIRequestResponseResolver:
    def __call__(
        self,
        request: Dict[str, Any],
        response: OpenAIResponse,
    ):
        if response["object"] == "edit":
            return self._resolve_edit(request, response)

    @staticmethod
    def results_to_trace_tree(
        request: Dict[str, Any],
        response: OpenAIResponse,
        results: List[trace_tree.Result],
    ) -> trace_tree.WBTraceTree:
        """Converts the request, response, and results into a trace tree.

        params:
            request: The request object
            response: The response object
            results: A list of results object
        returns:
            A trace tree object.
        """
        span = trace_tree.Span(
            name=f"{response.get('model', 'openai')}_{response['object']}_{response.get('created')}",
            attributes=dict(response),  # type: ignore
            start_time_ms=int(round(response["created"] * 1000)),
            end_time_ms=int(round(response["created"] * 1000)) + 10,
            span_kind=trace_tree.SpanKind.LLM,
            results=results,
        )
        model_obj = {"request": request, "response": response, "_kind": "openai"}
        return trace_tree.WBTraceTree(root_span=span, model_dict=model_obj)

    def _resolve_edit(
        self,
        request: Dict[str, Any],
        response: OpenAIResponse,
    ) -> trace_tree.WBTraceTree:
        def format_request(_request: Dict[str, Any]) -> str:
            """Formats the request object to a string.

            params:
                _request: The request object
            returns:
                A string representation of the request object to be logged in a trace tree Result object.
            """
            prompt = (
                f"\n\n**Instruction**: {_request['instruction']}\n\n"
                f"**Input**: {_request['input']}\n"
            )
            return prompt

        def format_response_choice(choice: Dict[str, Any]) -> str:
            """Formats the choice in a response object to a string.

            params:
                choice: The choice object
            returns:
                A string representation of the choice object to be logged in a trace tree Result object.
            """
            choice = f"\n\n**Edited**: {choice['text']}\n"
            return choice

        results = [
            trace_tree.Result(
                inputs={"request": format_request(request)},
                outputs={"response": format_response_choice(choice)},
            )
            for choice in response["choices"]
        ]
        trace = self.results_to_trace_tree(request, response, results)
        return trace


class Relay:
    def __init__(self) -> None:
        """Starts a local server that relays requests to the OpenAI API."""
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
        self.resolver = OpenAIRequestResponseResolver()

        # useful for debugging:
        # self.after_request_fn = self.app.after_request(self.after_request_fn)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop()

    @staticmethod
    def _get_free_port() -> int:
        """Returns a free port on the local machine."""
        sock = socket.socket()
        sock.bind(("", 0))

        _, port = sock.getsockname()
        return port

    def start(self) -> None:
        """Starts the local server in a separate thread."""
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
        """Stops the local server and restores the original OpenAI API URL."""
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
        """Relays a request to the OpenAI API and returns the response."""
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
        """Saves the request and response to the context."""
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
        trace = self.resolver(request_data, response_data)
        print(trace)

    def snoopy(self, subpath) -> Mapping[str, str]:
        """Relays a request to the OpenAI API, saves the context and returns the response."""
        # OpenAI API key must be set, otherwise we can't relay requests
        # We postpone this check for as long as possible
        if openai.api_key is None:
            raise wandb.errors.AuthenticationError("OpenAI API key must be set")

        request = flask.request
        with Timer() as timer:
            relayed_response = self.relay(request)

        # print("*****************")
        # print("REQUEST:")
        # print(request.get_json())
        # print("RESPONSE:")
        # print(relayed_response.status_code, relayed_response.json())
        # print("*****************")
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
