import dataclasses
import json
import logging
import socket
import sys
import threading
import traceback
import urllib.parse
from collections import defaultdict, deque
from copy import deepcopy
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Union,
)

import flask
import pandas as pd
import requests
import responses

import wandb
import wandb.util
from wandb.sdk.lib.timer import Timer

try:
    from typing import Literal, TypedDict
except ImportError:
    from typing_extensions import Literal, TypedDict

if sys.version_info >= (3, 8):
    from typing import Protocol
else:
    from typing_extensions import Protocol

if TYPE_CHECKING:
    from typing import Deque

    class RawRequestResponse(TypedDict):
        url: str
        request: Optional[Any]
        response: Dict[str, Any]
        time_elapsed: float  # seconds

    ResolverName = Literal[
        "upsert_bucket",
        "upload_files",
        "uploaded_files",
        "preempting",
        "upsert_sweep",
    ]

    class Resolver(TypedDict):
        name: ResolverName
        resolver: Callable[[Any], Optional[Dict[str, Any]]]


class DeliberateHTTPError(Exception):
    def __init__(self, message, status_code: int = 500):
        Exception.__init__(self)
        self.message = message
        self.status_code = status_code

    def get_response(self):
        return flask.Response(self.message, status=self.status_code)

    def __repr__(self):
        return f"DeliberateHTTPError({self.message!r}, {self.status_code!r})"


@dataclasses.dataclass
class RunAttrs:
    """Simple data class for run attributes."""

    name: str
    display_name: str
    description: str
    sweep_name: str
    project: Dict[str, Any]
    config: Dict[str, Any]
    remote: Optional[str] = None
    commit: Optional[str] = None


class Context:
    """A container used to store the snooped state/data of a test.

    Includes raw requests and responses, parsed and processed data, and a number of
    convenience methods and properties for accessing the data.
    """

    def __init__(self) -> None:
        # parsed/merged data. keys are the individual wandb run id's.
        self._entries = defaultdict(dict)
        # container for raw requests and responses:
        self.raw_data: List[RawRequestResponse] = []
        # concatenated file contents for all runs:
        self._history: Optional[pd.DataFrame] = None
        self._events: Optional[pd.DataFrame] = None
        self._summary: Optional[pd.DataFrame] = None
        self._config: Optional[Dict[str, Any]] = None
        self._output: Optional[Any] = None

    def upsert(self, entry: Dict[str, Any]) -> None:
        try:
            entry_id: str = entry["name"]
        except KeyError:
            entry_id = entry["id"]
        self._entries[entry_id] = wandb.util.merge_dicts(entry, self._entries[entry_id])

    # mapping interface
    def __getitem__(self, key: str) -> Any:
        return self._entries[key]

    def keys(self) -> Iterable[str]:
        return self._entries.keys()

    def get_file_contents(self, file_name: str) -> pd.DataFrame:
        dfs = []

        for entry_id in self._entries:
            # - extract the content from `file_name`
            # - sort by offset (will be useful when relay server goes async)
            # - extract data, merge into a list of dicts and convert to a pandas dataframe
            content_list = self._entries[entry_id].get("files", {}).get(file_name, [])
            content_list.sort(key=lambda x: x["offset"])
            content_list = [item["content"] for item in content_list]
            # merge list of lists content_list:
            content_list = [item for sublist in content_list for item in sublist]
            df = pd.DataFrame.from_records(content_list)
            df["__run_id"] = entry_id
            dfs.append(df)

        return pd.concat(dfs)

    # attributes to use in assertions
    @property
    def entries(self) -> Dict[str, Any]:
        return deepcopy(self._entries)

    @property
    def history(self) -> pd.DataFrame:
        # todo: caveat: this assumes that all assertions happen at the end of a test
        if self._history is not None:
            return deepcopy(self._history)

        self._history = self.get_file_contents("wandb-history.jsonl")
        return deepcopy(self._history)

    @property
    def events(self) -> pd.DataFrame:
        if self._events is not None:
            return deepcopy(self._events)

        self._events = self.get_file_contents("wandb-events.jsonl")
        return deepcopy(self._events)

    @property
    def summary(self) -> pd.DataFrame:
        if self._summary is not None:
            return deepcopy(self._summary)

        _summary = self.get_file_contents("wandb-summary.json")

        # run summary may be updated multiple times,
        # but we are only interested in the last one.
        # we can have multiple runs saved to context,
        # so we need to group by run id and take the
        # last one for each run.
        self._summary = (
            _summary.groupby("__run_id").last().reset_index(level=["__run_id"])
        )

        return deepcopy(self._summary)

    @property
    def output(self) -> pd.DataFrame:
        if self._output is not None:
            return deepcopy(self._output)

        self._output = self.get_file_contents("output.log")
        return deepcopy(self._output)

    @property
    def config(self) -> Dict[str, Any]:
        if self._config is not None:
            return deepcopy(self._config)

        self._config = {k: v["config"] for (k, v) in self._entries.items() if k}
        return deepcopy(self._config)

    # @property
    # def telemetry(self) -> pd.DataFrame:
    #     telemetry = pd.DataFrame.from_records(
    #         [
    #             {
    #                 "__run_id": run_id,
    #                 "telemetry": config.get("_wandb", {}).get("value", {}).get("t")
    #             }
    #             for (run_id, config) in self.config.items()
    #         ]
    #     )
    #     return telemetry

    # convenience data access methods
    def get_run_config(self, run_id: str) -> Dict[str, Any]:
        return self.config.get(run_id, {})

    def get_run_telemetry(self, run_id: str) -> Dict[str, Any]:
        return self.config.get(run_id, {}).get("_wandb", {}).get("value", {}).get("t")

    def get_run_metrics(self, run_id: str) -> Dict[str, Any]:
        return self.config.get(run_id, {}).get("_wandb", {}).get("value", {}).get("m")

    def get_run_summary(
        self, run_id: str, include_private: bool = False
    ) -> Dict[str, Any]:
        # run summary dataframe must have only one row
        # for the given run id, so we convert it to dict
        # and extract the first (and only) row.
        mask_run = self.summary["__run_id"] == run_id
        run_summary = self.summary[mask_run]
        ret = (
            run_summary.filter(regex="^[^_]", axis=1)
            if not include_private
            else run_summary
        ).to_dict(orient="records")
        return ret[0] if len(ret) > 0 else {}

    def get_run_history(
        self, run_id: str, include_private: bool = False
    ) -> pd.DataFrame:
        mask_run = self.history["__run_id"] == run_id
        run_history = self.history[mask_run]
        return (
            run_history.filter(regex="^[^_]", axis=1)
            if not include_private
            else run_history
        )

    def get_run_uploaded_files(self, run_id: str) -> Dict[str, Any]:
        return self.entries.get(run_id, {}).get("uploaded", [])

    def get_run_stats(self, run_id: str) -> pd.DataFrame:
        mask_run = self.events["__run_id"] == run_id
        run_stats = self.events[mask_run]
        return run_stats

    def get_run_attrs(self, run_id: str) -> Optional[RunAttrs]:
        run_entry = self._entries.get(run_id)
        if not run_entry:
            return None

        return RunAttrs(
            name=run_entry["name"],
            display_name=run_entry["displayName"],
            description=run_entry["description"],
            sweep_name=run_entry["sweepName"],
            project=run_entry["project"],
            config=run_entry["config"],
            remote=run_entry.get("repo"),
            commit=run_entry.get("commit"),
        )

    def get_run(self, run_id: str) -> Dict[str, Any]:
        return self._entries.get(run_id, {})

    def get_run_ids(self) -> List[str]:
        return [k for k in self._entries.keys() if k]

    # todo: add getter (by run_id) utilities for other properties


class QueryResolver:
    """Resolve request/response pairs against a set of known patterns.

    This extracts and processes useful data to be later stored in a Context object.
    """

    def __init__(self):
        self.resolvers: List[Resolver] = [
            {
                "name": "upsert_bucket",
                "resolver": self.resolve_upsert_bucket,
            },
            {
                "name": "upload_files",
                "resolver": self.resolve_upload_files,
            },
            {
                "name": "uploaded_files",
                "resolver": self.resolve_uploaded_files,
            },
            {
                "name": "uploaded_files_legacy",
                "resolver": self.resolve_uploaded_files_legacy,
            },
            {
                "name": "preempting",
                "resolver": self.resolve_preempting,
            },
            {
                "name": "upsert_sweep",
                "resolver": self.resolve_upsert_sweep,
            },
            {
                "name": "create_artifact",
                "resolver": self.resolve_create_artifact,
            },
            {
                "name": "delete_run",
                "resolver": self.resolve_delete_run,
            },
        ]

    @staticmethod
    def resolve_upsert_bucket(
        request_data: Dict[str, Any], response_data: Dict[str, Any], **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(request_data, dict) or not isinstance(response_data, dict):
            return None
        query = response_data.get("data", {}).get("upsertBucket") is not None
        if query:
            data = {
                k: v for (k, v) in request_data["variables"].items() if v is not None
            }
            data.update(response_data["data"]["upsertBucket"].get("bucket"))
            if "config" in data:
                data["config"] = json.loads(data["config"])
            return data
        return None

    @staticmethod
    def resolve_delete_run(
        request_data: Dict[str, Any], response_data: Dict[str, Any], **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(request_data, dict) or not isinstance(response_data, dict):
            return None
        query = "query" in request_data and "deleteRun" in request_data["query"]
        if query:
            data = {
                k: v for (k, v) in request_data["variables"].items() if v is not None
            }
            data.update(response_data["data"]["deleteRun"])
            return data
        return None

    @staticmethod
    def resolve_upload_files(
        request_data: Dict[str, Any], response_data: Dict[str, Any], **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(request_data, dict):
            return None

        query = request_data.get("files") is not None
        if query:
            # todo: refactor this 🤮🤮🤮🤮🤮 eventually?
            name = kwargs.get("path").split("/")[2]
            files = defaultdict(list)
            for file_name, file_value in request_data["files"].items():
                content = []
                for k in file_value.get("content", []):
                    try:
                        content.append(json.loads(k))
                    except json.decoder.JSONDecodeError:
                        content.append([k])

                files[file_name].append(
                    {"offset": file_value.get("offset"), "content": content}
                )

            post_processed_data = {
                "name": name,
                "dropped": [request_data["dropped"]]
                if "dropped" in request_data
                else [],
                "files": files,
            }
            return post_processed_data
        return None

    @staticmethod
    def resolve_uploaded_files(
        request_data: Dict[str, Any], response_data: Dict[str, Any], **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(request_data, dict) or not isinstance(response_data, dict):
            return None

        query = "CreateRunFiles" in request_data.get("query", "")
        if query:
            run_name = request_data["variables"]["run"]
            files = ((response_data.get("data") or {}).get("createRunFiles") or {}).get(
                "files", {}
            )
            post_processed_data = {
                "name": run_name,
                "uploaded": [file["name"] for file in files] if files else [""],
            }
            return post_processed_data
        return None

    @staticmethod
    def resolve_uploaded_files_legacy(
        request_data: Dict[str, Any], response_data: Dict[str, Any], **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        # This is a legacy resolver for uploaded files
        # No longer used by tests but leaving it here in case we need it in the future
        # Please refer to upload_urls() in internal_api.py for more details
        if not isinstance(request_data, dict) or not isinstance(response_data, dict):
            return None

        query = "RunUploadUrls" in request_data.get("query", "")
        if query:
            # todo: refactor this 🤮🤮🤮🤮🤮 eventually?
            name = request_data["variables"]["run"]
            files = (
                response_data.get("data", {})
                .get("model", {})
                .get("bucket", {})
                .get("files", {})
                .get("edges", [])
            )
            # note: we count all attempts to upload files
            post_processed_data = {
                "name": name,
                "uploaded": [files[0].get("node", {}).get("name")] if files else [""],
            }
            return post_processed_data
        return None

    @staticmethod
    def resolve_preempting(
        request_data: Dict[str, Any], response_data: Dict[str, Any], **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(request_data, dict):
            return None
        query = "preempting" in request_data
        if query:
            name = kwargs.get("path").split("/")[2]
            post_processed_data = {
                "name": name,
                "preempting": [request_data["preempting"]],
            }
            return post_processed_data
        return None

    @staticmethod
    def resolve_upsert_sweep(
        request_data: Dict[str, Any], response_data: Dict[str, Any], **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(response_data, dict):
            return None
        query = response_data.get("data", {}).get("upsertSweep") is not None
        if query:
            data = response_data["data"]["upsertSweep"].get("sweep")
            return data
        return None

    def resolve_create_artifact(
        self, request_data: Dict[str, Any], response_data: Dict[str, Any], **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(request_data, dict):
            return None
        query = (
            "createArtifact(" in request_data.get("query", "")
            and request_data.get("variables") is not None
            and response_data is not None
        )
        if query:
            name = request_data["variables"]["runName"]
            post_processed_data = {
                "name": name,
                "create_artifact": [
                    {
                        "variables": request_data["variables"],
                        "response": response_data["data"]["createArtifact"]["artifact"],
                    }
                ],
            }
            return post_processed_data
        return None

    def resolve(
        self,
        request_data: Dict[str, Any],
        response_data: Dict[str, Any],
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        results = []
        for resolver in self.resolvers:
            result = resolver.get("resolver")(request_data, response_data, **kwargs)
            if result is not None:
                results.append(result)
        return results


class TokenizedCircularPattern:
    APPLY_TOKEN = "1"
    PASS_TOKEN = "0"
    STOP_TOKEN = "2"

    def __init__(self, pattern: str):
        known_tokens = {self.APPLY_TOKEN, self.PASS_TOKEN, self.STOP_TOKEN}
        if not pattern:
            raise ValueError("Pattern cannot be empty")

        if set(pattern) - known_tokens:
            raise ValueError(f"Pattern can only contain {known_tokens}")
        self.pattern: Deque[str] = deque(pattern)

    def next(self):
        if self.pattern[0] == self.STOP_TOKEN:
            return
        self.pattern.rotate(-1)

    def should_apply(self) -> bool:
        return self.pattern[0] == self.APPLY_TOKEN


@dataclasses.dataclass
class InjectedResponse:
    method: str
    url: str
    body: Union[str, Exception]
    status: int = 200
    content_type: str = "text/plain"
    # todo: add more fields for other types of responses?
    custom_match_fn: Optional[Callable[..., bool]] = None
    application_pattern: TokenizedCircularPattern = TokenizedCircularPattern("1")

    # application_pattern defines the pattern of the response injection
    # as the requests come in.
    # 0 == do not inject the response
    # 1 == inject the response
    # 2 == stop using the response (END token)
    #
    # - when no END token is present, the pattern is repeated indefinitely
    # - when END token is present, the pattern is applied until the END token is reached
    # - to replicate the current behavior:
    #  - use application_pattern = "1" if wanting to apply the pattern to all requests
    #  - use application_pattern = "1" * COUNTER + "2" to apply the pattern to the first COUNTER requests
    #
    # Examples of application_pattern:
    # 1. application_pattern = "1012"
    #    - inject the response for the first request
    #    - do not inject the response for the second request
    #    - inject the response for the third request
    #    - stop using the response starting from the fourth request onwards
    # 2. application_pattern = "110"
    #    repeat the following pattern indefinitely:
    #    - inject the response for the first request
    #    - inject the response for the second request
    #    - stop using the response for the third request

    def __eq__(
        self,
        other: Union["InjectedResponse", requests.Request, requests.PreparedRequest],
    ):
        """Check InjectedResponse object equality.

        We use this to check if this response should be injected as a replacement of
        `other`.

        :param other:
        :return:
        """
        if not isinstance(
            other, (InjectedResponse, requests.Request, requests.PreparedRequest)
        ):
            return False

        # always check the method and url
        ret = self.method == other.method and self.url == other.url
        # use custom_match_fn to check, e.g. the request body content
        if ret and self.custom_match_fn is not None:
            ret = self.custom_match_fn(self, other)
        return ret

    def to_dict(self):
        excluded_fields = {"application_pattern", "custom_match_fn"}
        return {
            k: self.__getattribute__(k)
            for k in self.__dict__
            if (not k.startswith("_") and k not in excluded_fields)
        }


class RelayControlProtocol(Protocol):
    def process(self, request: "flask.Request") -> None: ...  # pragma: no cover

    def control(
        self, request: "flask.Request"
    ) -> Mapping[str, str]: ...  # pragma: no cover


class RelayServer:
    def __init__(
        self,
        base_url: str,
        inject: Optional[List[InjectedResponse]] = None,
        control: Optional[RelayControlProtocol] = None,
        verbose: bool = False,
    ) -> None:
        # todo for the future:
        #  - consider switching from Flask to Quart
        #  - async app will allow for better failure injection/poor network perf
        self.relay_control = control
        self.app = flask.Flask(__name__)
        self.app.logger.setLevel(logging.INFO)
        self.app.register_error_handler(DeliberateHTTPError, self.handle_http_exception)
        self.app.add_url_rule(
            rule="/graphql",
            endpoint="graphql",
            view_func=self.graphql,
            methods=["POST"],
        )
        self.app.add_url_rule(
            rule="/files/<path:path>",
            endpoint="files",
            view_func=self.file_stream,
            methods=["POST"],
        )
        self.app.add_url_rule(
            rule="/storage",
            endpoint="storage",
            view_func=self.storage,
            methods=["PUT", "GET"],
        )
        self.app.add_url_rule(
            rule="/storage/<path:path>",
            endpoint="storage_file",
            view_func=self.storage_file,
            methods=["PUT", "GET"],
        )
        if control:
            self.app.add_url_rule(
                rule="/_control",
                endpoint="_control",
                view_func=self.control,
                methods=["POST"],
            )
        # @app.route("/artifacts/<entity>/<digest>", methods=["GET", "POST"])
        self.port = self._get_free_port()
        self.base_url = urllib.parse.urlparse(base_url)
        self.session = requests.Session()
        self.relay_url = f"http://127.0.0.1:{self.port}"

        # todo: add an option to add custom resolvers
        self.resolver = QueryResolver()
        # recursively merge-able object to store state
        self.context = Context()

        # injected responses
        self.inject = inject or []

        # useful when debugging:
        # self.after_request_fn = self.app.after_request(self.after_request_fn)
        self.verbose = verbose

    @staticmethod
    def handle_http_exception(e):
        response = e.get_response()
        return response

    @staticmethod
    def _get_free_port() -> int:
        sock = socket.socket()
        sock.bind(("", 0))

        _, port = sock.getsockname()
        return port

    def start(self) -> None:
        # run server in a separate thread
        relay_server_thread = threading.Thread(
            target=self.app.run,
            kwargs={"port": self.port},
            daemon=True,
        )
        relay_server_thread.start()

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
    ) -> Union["responses.Response", "requests.Response", None]:
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

        if self.verbose:
            print("*****************")
            print("RELAY REQUEST:")
            print(prepared_relayed_request.url)
            print(prepared_relayed_request.method)
            print(prepared_relayed_request.headers)
            print(prepared_relayed_request.body)
            print("*****************")

        for injected_response in self.inject:
            # where are we in the application pattern?
            should_apply = injected_response.application_pattern.should_apply()
            # check if an injected response matches the request
            if injected_response != prepared_relayed_request or not should_apply:
                continue

            if self.verbose:
                print("*****************")
                print("INJECTING RESPONSE:")
                print(injected_response.to_dict())
                print("*****************")
            # rotate the injection pattern
            injected_response.application_pattern.next()

            # TODO: allow access to the request object when making the mocked response
            with responses.RequestsMock() as mocked_responses:
                # do the actual injection
                resp = injected_response.to_dict()

                if isinstance(resp["body"], ConnectionResetError):
                    return None

                mocked_responses.add(**resp)
                relayed_response = self.session.send(prepared_relayed_request)

                return relayed_response

        # normal case: no injected response matches the request
        relayed_response = self.session.send(prepared_relayed_request)
        return relayed_response

    def snoop_context(
        self,
        request: "flask.Request",
        response: "requests.Response",
        time_elapsed: float,
        **kwargs: Any,
    ) -> None:
        request_data = request.get_json()
        response_data = response.json() or {}

        if self.relay_control:
            self.relay_control.process(request)

        # store raw data
        raw_data: RawRequestResponse = {
            "url": request.url,
            "request": request_data,
            "response": response_data,
            "time_elapsed": time_elapsed,
        }
        self.context.raw_data.append(raw_data)

        try:
            snooped_context = self.resolver.resolve(
                request_data,
                response_data,
                **kwargs,
            )
            for entry in snooped_context:
                self.context.upsert(entry)
        except Exception as e:
            print("Failed to resolve context: ", e)
            traceback.print_exc()
            snooped_context = None

        return None

    def graphql(self) -> Mapping[str, str]:
        request = flask.request
        with Timer() as timer:
            relayed_response = self.relay(request)
        if self.verbose:
            print("*****************")
            print("GRAPHQL REQUEST:")
            print(request.get_json())
            print("GRAPHQL RESPONSE:")
            print(relayed_response.status_code, relayed_response.json())
            print("*****************")
        # snoop work to extract the context
        self.snoop_context(request, relayed_response, timer.elapsed)
        if self.verbose:
            print("*****************")
            print("SNOOPED CONTEXT:")
            print(self.context.entries)
            print(len(self.context.raw_data))
            print("*****************")

        return relayed_response.json()

    def file_stream(self, path) -> Mapping[str, str]:
        request = flask.request

        with Timer() as timer:
            relayed_response = self.relay(request)

        # simulate connection reset by peer
        if relayed_response is None:
            connection = request.environ["werkzeug.socket"]  # Get the socket object
            connection.shutdown(socket.SHUT_RDWR)
            connection.close()

        if self.verbose:
            print("*****************")
            print("FILE STREAM REQUEST:")
            print("********PATH*********")
            print(path)
            print("********ENDPATH*********")
            print(request.get_json())
            print("FILE STREAM RESPONSE:")
            print(relayed_response)
            print(relayed_response.status_code, relayed_response.json())
            print("*****************")
        self.snoop_context(request, relayed_response, timer.elapsed, path=path)

        return relayed_response.json()

    def storage(self) -> Mapping[str, str]:
        request = flask.request
        with Timer() as timer:
            relayed_response = self.relay(request)
        if self.verbose:
            print("*****************")
            print("STORAGE REQUEST:")
            print(request.get_json())
            print("STORAGE RESPONSE:")
            print(relayed_response.status_code, relayed_response.json())
            print("*****************")

        self.snoop_context(request, relayed_response, timer.elapsed)

        return relayed_response.json()

    def storage_file(self, path) -> Mapping[str, str]:
        request = flask.request
        with Timer() as timer:
            relayed_response = self.relay(request)
        if self.verbose:
            print("*****************")
            print("STORAGE FILE REQUEST:")
            print("********PATH*********")
            print(path)
            print("********ENDPATH*********")
            print(request.get_json())
            print("STORAGE FILE RESPONSE:")
            print(relayed_response.json())
            print("*****************")

        self.snoop_context(request, relayed_response, timer.elapsed, path=path)

        return relayed_response.json()

    def control(self) -> Mapping[str, str]:
        assert self.relay_control
        return self.relay_control.control(flask.request)
