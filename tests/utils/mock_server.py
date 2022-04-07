"""Mock Server for simple calls the cli and public api make"""

from flask import Flask, request, g, jsonify
import os
import sys
import re
from datetime import datetime, timedelta
import json
import platform
import yaml
import six
import gzip
import functools
import time
import requests
from werkzeug.exceptions import BadRequest

# HACK: restore first two entries of sys path after wandb load
save_path = sys.path[:2]
import wandb

sys.path[0:0] = save_path
import logging
from six.moves import urllib
import threading

RequestsMock = None
InjectRequestsParse = None
ArtifactEmulator = None


def load_modules(use_yea=False):
    global RequestsMock, InjectRequestsParse, ArtifactEmulator
    if use_yea:
        from yea_wandb.mock_requests import RequestsMock, InjectRequestsParse
        from yea_wandb.artifact_emu import ArtifactEmulator
    else:
        from tests.utils.mock_requests import RequestsMock, InjectRequestsParse
        from tests.utils.artifact_emu import ArtifactEmulator


# global (is this safe?)
ART_EMU = None


def default_ctx():
    return {
        "fail_graphql_count": 0,  # used via "fail_graphql_times"
        "fail_storage_count": 0,  # used via "fail_storage_times"
        "rate_limited_count": 0,  # used via "rate_limited_times"
        "graphql_conflict": False,
        "num_search_users": 1,
        "page_count": 0,
        "page_times": 2,
        "requested_file": "weights.h5",
        "current_run": None,
        "files": {},
        "k8s": False,
        "resume": None,
        "file_bytes": {},
        "manifests_created": [],
        "artifacts": {},
        "artifacts_by_id": {},
        "artifacts_created": {},
        "portfolio_links": {},
        "upsert_bucket_count": 0,
        "out_of_date": False,
        "empty_query": False,
        "local_none": False,
        "run_queues_return_default": True,
        "run_queues": {"1": []},
        "num_popped": 0,
        "num_acked": 0,
        "max_cli_version": "0.13.0",
        "runs": {},
        "run_ids": [],
        "file_names": [],
        "emulate_artifacts": None,
        "emulate_azure": False,
        "run_state": "running",
        "run_queue_item_check_count": 0,
        "return_jupyter_in_run_info": False,
        "alerts": [],
        "gorilla_supports_launch_agents": True,
        "launch_agents": {},
        "successfully_create_default_queue": True,
        "launch_agent_update_fail": False,
        "stop_launch_agent": False,
        "swappable_artifacts": False,
        "used_artifact_info": None,
        "invalid_launch_spec_project": False,
        "n_sweep_runs": 0,
        "code_saving_enabled": True,
        "sentry_events": [],
        "run_cuda_version": None,
        # relay mode, keep track of upsert runs for validation
        "relay_run_info": {},
    }


def mock_server(mocker):
    load_modules()
    ctx = default_ctx()
    app = create_app(ctx)
    mock = RequestsMock(app, ctx)
    # We mock out all requests libraries, couldn't find a way to mock the core lib
    sdk_path = "wandb.sdk"
    mocker.patch("wandb_gql.transport.requests.requests", mock)
    mocker.patch("wandb.wandb_sdk.internal.file_stream.requests", mock)
    mocker.patch("wandb.wandb_sdk.internal.internal_api.requests", mock)
    mocker.patch("wandb.wandb_sdk.internal.update.requests", mock)
    mocker.patch("wandb.wandb_sdk.internal.sender.requests", mock)
    mocker.patch("wandb.apis.public.requests", mock)
    mocker.patch("wandb.util.requests", mock)
    mocker.patch("wandb.wandb_sdk.wandb_artifacts.requests", mock)
    mocker.patch("azure.core.pipeline.transport._requests_basic.requests", mock)
    print("Patched requests everywhere", os.getpid())
    return mock


def run(ctx):
    if ctx["resume"]:
        now = datetime.now()
        created_at = (now - timedelta(days=1)).isoformat()
    else:
        created_at = datetime.now().isoformat()

    stopped = ctx.get("stopped", False)
    base_url = request.url_root.rstrip("/")

    # for wandb_tests::wandb_restore_name_not_found
    # if there is a fileName query, and this query is for nofile.h5
    # return an empty file. otherwise, return the usual weights.h5
    if ctx.get("graphql"):
        fileNames = ctx["graphql"][-1]["variables"].get("fileNames")
    else:
        fileNames = None
    if fileNames == ["nofile.h5"]:
        fileNode = {
            "id": "file123",
            "name": "nofile.h5",
            "sizeBytes": 0,
            "md5": "0",
            "url": base_url + "/storage?file=nofile.h5",
        }
    else:
        fileNode = {
            "id": "file123",
            "name": ctx["requested_file"],
            "sizeBytes": 20,
            "md5": "XXX",
            "url": base_url + "/storage?file=%s" % ctx["requested_file"],
            "directUrl": base_url
            + "/storage?file=%s&direct=true" % ctx["requested_file"],
        }
    if ctx["return_jupyter_in_run_info"]:
        program_name = "one_cell.ipynb"
    else:
        program_name = "train.py"
    return {
        "id": "test",
        "name": "test",
        "displayName": "beast-bug-33",
        "state": "running",
        "config": '{"epochs": {"value": 10}}',
        "group": "A",
        "jobType": "test",
        "description": "",
        "systemMetrics": '{"cpu": 100}',
        "summaryMetrics": '{"acc": 100, "loss": 0}',
        "fileCount": 1,
        "history": [
            '{"acc": 10, "loss": 90}',
            '{"acc": 20, "loss": 80}',
            '{"acc": 30, "loss": 70}',
        ],
        "events": ['{"cpu": 10}', '{"cpu": 20}', '{"cpu": 30}'],
        "files": {
            # Special weights url by default, if requesting upload we set the name
            "edges": [
                {
                    "node": fileNode,
                }
            ]
        },
        "sampledHistory": [[{"loss": 0, "acc": 100}, {"loss": 1, "acc": 0}]],
        "shouldStop": False,
        "failed": False,
        "stopped": stopped,
        "running": True,
        "tags": [],
        "notes": None,
        "sweepName": None,
        "createdAt": created_at,
        "updatedAt": datetime.now().isoformat(),
        "runInfo": {
            "program": program_name,
            "args": [],
            "os": platform.system(),
            "python": platform.python_version(),
            "colab": None,
            "executable": None,
            "codeSaved": False,
            "cpuCount": 12,
            "gpuCount": 0,
            "git": {
                "remote": "https://foo:bar@github.com/FooTest/Foo.git",
                "commit": "HEAD",
            },
        },
    }


def artifact(
    ctx,
    collection_name="mnist",
    state="COMMITTED",
    request_url_root="",
    id_override=None,
):
    _id = str(ctx["page_count"]) if id_override is None else id_override
    return {
        "id": _id,
        "digest": "abc123",
        "description": "",
        "state": state,
        "size": 10000,
        "createdAt": datetime.now().isoformat(),
        "updatedAt": datetime.now().isoformat(),
        "versionIndex": ctx["page_count"],
        "labels": [],
        "metadata": "{}",
        "aliases": [
            {
                "artifactCollectionName": collection_name,
                "alias": "v%i" % ctx["page_count"],
            }
        ],
        "artifactSequence": {
            "name": collection_name,
        },
        "artifactType": {"name": "dataset"},
        "currentManifest": {
            "file": {
                "directUrl": request_url_root
                + "/storage?file=wandb_manifest.json&id={}".format(_id)
            }
        },
    }


def paginated(node, ctx, extra={}):
    next_page = False
    ctx["page_count"] += 1
    if ctx["page_count"] < ctx["page_times"]:
        next_page = True
    edge = {"node": node, "cursor": "abc123"}
    edge.update(extra)
    return {
        "edges": [edge],
        "pageInfo": {"endCursor": "abc123", "hasNextPage": next_page},
    }


class CTX(object):
    """This is a silly threadsafe wrapper for getting ctx into the server
    NOTE: This will stop working for live_mock_server if we make pytest run
    in parallel.
    """

    lock = threading.Lock()
    STATE = None

    def __init__(self, ctx):
        self.ctx = ctx

    def get(self):
        return self.ctx

    def set(self, ctx):
        self.ctx = ctx
        CTX.persist(self)
        return self.ctx

    @classmethod
    def persist(cls, instance):
        with cls.lock:
            cls.STATE = instance.ctx

    @classmethod
    def load(cls, default):
        with cls.lock:
            if cls.STATE is not None:
                return CTX(cls.STATE)
            else:
                return CTX(default)


def get_ctx():
    if "ctx" not in g:
        g.ctx = CTX.load(default_ctx())
    return g.ctx.get()


def get_run_ctx(run_id):
    glob_ctx = get_ctx()
    run_ctx = glob_ctx["runs"][run_id]
    return run_ctx


def set_ctx(ctx):
    get_ctx()
    g.ctx.set(ctx)


def _bucket_config(ctx):
    files = ["wandb-metadata.json", "diff.patch"]
    if "bucket_config" in ctx and "files" in ctx["bucket_config"]:
        files = ctx["bucket_config"]["files"]
    base_url = request.url_root.rstrip("/")
    return {
        "commit": "HEAD",
        "github": "https://github.com/vanpelt",
        "config": '{"foo":{"value":"bar"}}',
        "files": {
            "edges": [
                {
                    "node": {
                        "url": base_url + "/storage?file=" + name,
                        "directUrl": base_url
                        + "/storage?file="
                        + name
                        + "&direct=true",
                        "updatedAt": datetime.now().isoformat(),
                        "name": name,
                    }
                }
                for name in files
            ]
        },
    }


class HttpException(Exception):
    status_code = 500

    def __init__(self, message, status_code=None, payload=None):
        Exception.__init__(self)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.payload = payload

    def to_dict(self):
        rv = dict(self.payload or ())
        rv["error"] = self.message
        return rv


class SnoopRelay:

    _inject_count: int
    _inject_time: float

    def __init__(self):
        self._inject_count = 0
        self._inject_time = 0.0

    def relay(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):

            # Normal mockserver mode, disable live relay and call next function
            if not os.environ.get("MOCKSERVER_RELAY"):
                return func(*args, **kwargs)

            if request.method == "POST":
                url_path = request.path
                body = request.get_json()

                url = f"https://api.wandb.ai{url_path}"
                resp = requests.post(url, json=body)
                data = resp.json()
                run_obj = data.get("data", {}).get("upsertBucket", {}).get("bucket", {})
                project_obj = run_obj.get("project", {})

                run_id = run_obj.get("name")
                project = project_obj.get("name")
                entity = project_obj.get("entity", {}).get("name")

                ctx = get_ctx()
                if run_id:
                    ctx["relay_run_info"].setdefault(run_id, {})
                    ctx["relay_run_info"][run_id]["project"] = project
                    ctx["relay_run_info"][run_id]["entity"] = entity

                # TODO: This is a hardcoded for now, will add inject specification to the yea file
                if run_id and run_id.startswith("inject"):
                    time_now = time.time()
                    if self._inject_count == 0:
                        self._inject_time = time_now
                    self._inject_count += 1
                    if time_now < self._inject_time + 21:
                        # print("INJECT", self._inject_count, time_now, self._inject_time)
                        time.sleep(12)
                        raise HttpException("some error", status_code=500)
                return data
            assert False

            return func(*args, **kwargs)

        return wrapper

    def context_enrich(self, ctx):
        for run_id, run_info in ctx["relay_run_info"].items():
            run_num = len(ctx["runs"])
            insert = run_id not in ctx["run_ids"]
            if insert:
                ctx["run_ids"].append(run_id)
            run_ctx = ctx["runs"].setdefault(run_id, default_ctx())

            # NOTE: not used, added for consistancy with non-relay mode
            r = run_ctx.setdefault("run", {})
            r.setdefault("display_name", f"relay_name-{run_num}")
            r.setdefault("storage_id", f"storageid{run_num}")
            r.setdefault("project_name", "relay_proj")
            r.setdefault("entity_name", "relay_entity")

            # TODO: handle errors better
            try:
                # NOTE: We are using wandb but it isnt a strict depenedency
                import wandb

                api = wandb.Api()
                run = api.run(f"{run_info['entity']}/{run_info['project']}/{run_id}")
            except Exception as e:
                print(f"ERROR: problem calling public api for run {run_id}", e)
                continue

            value_config = {k: dict(value=v) for k, v in run.rawconfig.items()}
            # TODO: need to have a correct state mapping
            exitcode = 0 if run.state == "finished" else 1

            for c in ctx, run_ctx:
                c.setdefault("config", []).append(dict(value_config))
                c.setdefault("file_stream", []).append(
                    dict(
                        exitcode=exitcode,
                        files={
                            "wandb-summary.json": dict(
                                offset=0, content=[json.dumps(run.summary_metrics)]
                            )
                        },
                    )
                )
            ctx["runs"][run_id] = run_ctx
        # print("SEND", ctx)
        return ctx


def create_app(user_ctx=None):
    app = Flask(__name__)
    # When starting in live mode, user_ctx is a fancy object
    if isinstance(user_ctx, dict):
        with app.app_context():
            set_ctx(user_ctx)
    snoop = SnoopRelay()

    @app.teardown_appcontext
    def persist_ctx(exc):
        if "ctx" in g:
            CTX.persist(g.ctx)

    @app.errorhandler(HttpException)
    def handle_http_exception(error):
        response = jsonify(error.to_dict())
        # For azure storage
        response.headers["x-ms-error-code"] = 500
        response.status_code = error.status_code
        return response

    @app.route("/ctx", methods=["GET", "PUT", "DELETE"])
    def update_ctx():
        """Updating context for live_mock_server"""
        ctx = get_ctx()
        # in Flask/Werkzeug 2.1.0 get_json raises an exception on
        # empty json, so we try/catch here
        try:
            body = request.get_json()
        except BadRequest:
            body = None

        if request.method == "GET":
            ctx = snoop.context_enrich(ctx)
            return json.dumps(ctx)
        elif request.method == "DELETE":
            app.logger.info("reseting context")
            set_ctx(default_ctx())
            return json.dumps(get_ctx())
        else:
            ctx.update(body)
            # TODO: tests in CI failed on this
            set_ctx(ctx)
            app.logger.info("updated context %s", ctx)
            return json.dumps(get_ctx())

    @app.route("/graphql", methods=["POST"])
    @snoop.relay
    def graphql():
        #  TODO: in tests wandb-username is set to the test name, lets scope ctx to it
        ctx = get_ctx()
        base_url = request.url_root.rstrip("/")
        test_name = request.headers.get("X-WANDB-USERNAME")
        if test_name:
            app.logger.info("Test request from: %s", test_name)
        app.logger.info("graphql post")

        if "fail_graphql_times" in ctx:
            if ctx["fail_graphql_count"] < ctx["fail_graphql_times"]:
                ctx["fail_graphql_count"] += 1
                return json.dumps({"errors": ["Server down"]}), 500
        if "rate_limited_times" in ctx:
            if ctx["rate_limited_count"] < ctx["rate_limited_times"]:
                ctx["rate_limited_count"] += 1
                return json.dumps({"error": "rate limit exceeded"}), 429
        if ctx["graphql_conflict"]:
            return json.dumps({"error": "resource already exists"}), 409

        # Setup artifact emulator (should this be somewhere else?)
        emulate_random_str = ctx["emulate_artifacts"]
        global ART_EMU
        if emulate_random_str:
            if ART_EMU is None or ART_EMU._random_str != emulate_random_str:
                ART_EMU = ArtifactEmulator(
                    random_str=emulate_random_str, ctx=ctx, base_url=base_url
                )
        else:
            ART_EMU = None

        body = request.get_json()
        app.logger.info("graphql post body: %s", body)

        if body["variables"].get("run"):
            ctx["current_run"] = body["variables"]["run"]

        if body["variables"].get("files"):
            requested_file = body["variables"]["files"][0]
            ctx["requested_file"] = requested_file
            emulate_azure = ctx.get("emulate_azure")
            # Azure expects the request path of signed urls to have 2 parts
            upload_headers = []
            if emulate_azure:
                url = (
                    base_url
                    + "/storage/azure/"
                    + ctx["current_run"]
                    + "/"
                    + requested_file
                )
                upload_headers.append("x-ms-blob-type:Block")
                upload_headers.append("Content-MD5:{}".format("AAAA"))
            else:
                url = base_url + "/storage?file={}&run={}".format(
                    urllib.parse.quote(requested_file), ctx["current_run"]
                )
            return json.dumps(
                {
                    "data": {
                        "model": {
                            "bucket": {
                                "id": "storageid",
                                "files": {
                                    "uploadHeaders": upload_headers,
                                    "edges": [
                                        {
                                            "node": {
                                                "name": requested_file,
                                                "url": url,
                                                "directUrl": url + "&direct=true",
                                            }
                                        }
                                    ],
                                },
                            }
                        }
                    }
                }
            )
        if "historyTail" in body["query"]:
            if ctx["resume"] is True:
                hist_tail = '["{\\"_step\\": 15, \\"acc\\": 1, \\"_runtime\\": 60}"]'
                return json.dumps(
                    {
                        "data": {
                            "model": {
                                "bucket": {
                                    "name": "test",
                                    "displayName": "funky-town-13",
                                    "id": "test",
                                    "config": '{"epochs": {"value": 10}}',
                                    "summaryMetrics": '{"acc": 10, "best_val_loss": 0.5, "_wandb": {"runtime": 50}}',
                                    "logLineCount": 14,
                                    "historyLineCount": 15,
                                    "eventsLineCount": 0,
                                    "historyTail": hist_tail,
                                    "eventsTail": '["{\\"_runtime\\": 70}"]',
                                }
                            }
                        }
                    }
                )
            else:
                return json.dumps({"data": {"model": {"bucket": None}}})
        if "query Runs(" in body["query"]:
            return json.dumps(
                {
                    "data": {
                        "project": {
                            "runCount": 4,
                            "readOnly": False,
                            "runs": paginated(run(ctx), ctx),
                        }
                    }
                }
            )
        if "reportCursor" in body["query"]:
            page_count = ctx["page_count"]
            return json.dumps(
                {
                    "data": {
                        "project": {
                            "allViews": paginated(
                                {
                                    "name": "test-report",
                                    "description": "test-description",
                                    "user": {
                                        "username": body["variables"]["entity"],
                                        "photoUrl": "test-url",
                                    },
                                    "spec": '{"version": 5}',
                                    "updatedAt": datetime.now().isoformat(),
                                    "pageCount": page_count,
                                },
                                ctx,
                            )
                        }
                    }
                }
            )
        for query_name in [
            "Run",
            "RunInfo",
            "RunState",
            "RunFiles",
            "RunFullHistory",
            "RunSampledHistory",
        ]:
            if f"query {query_name}(" in body["query"]:
                # if querying state of run, change context from running to finished
                if "RunFragment" not in body["query"] and "state" in body["query"]:
                    ret_val = json.dumps(
                        {"data": {"project": {"run": {"state": ctx.get("run_state")}}}}
                    )
                    ctx["run_state"] = "finished"
                    return ret_val
                return json.dumps({"data": {"project": {"run": run(ctx)}}})
        for query_name in [
            "Model",  # backward compatible for 0.12.10 and below
            "RunConfigs",
            "RunResumeStatus",
            "RunStoppedStatus",
            "RunUploadUrls",
            "RunDownloadUrls",
            "RunDownloadUrl",
        ]:
            if f"query {query_name}(" in body["query"]:
                if "project(" in body["query"]:
                    project_field_name = "project"
                    run_field_name = "run"
                else:
                    project_field_name = "model"
                    run_field_name = "bucket"
                if (
                    "commit" in body["query"]
                    or body["variables"].get("fileName") == "wandb-metadata.json"
                ):
                    run_config = _bucket_config(ctx)
                else:
                    run_config = run(ctx)
                return json.dumps(
                    {"data": {project_field_name: {run_field_name: run_config}}}
                )
        # Models() is backward compatible for 0.12.10 and below
        if "query Models(" in body["query"] or "query EntityProjects(" in body["query"]:
            return json.dumps(
                {
                    "data": {
                        "models": {
                            "edges": [
                                {
                                    "node": {
                                        "id": "123",
                                        "name": "myname",
                                        "project": "myproj",
                                    }
                                }
                            ]
                        }
                    }
                }
            )
        if "query Projects(" in body["query"]:
            return json.dumps(
                {
                    "data": {
                        "models": paginated(
                            {
                                "id": "1",
                                "name": "test-project",
                                "entityName": body["variables"]["entity"],
                                "createdAt": "now",
                                "isBenchmark": False,
                            },
                            ctx,
                        )
                    }
                }
            )
        if "query Viewer " in body["query"]:
            viewer_dict = {
                "data": {
                    "viewer": {
                        "entity": "mock_server_entity",
                        "admin": False,
                        "email": "mock@server.test",
                        "username": "mock",
                        "teams": {"edges": []},  # TODO make configurable for cli_test
                    },
                },
            }
            code_saving_enabled = ctx.get("code_saving_enabled")
            if code_saving_enabled is not None:
                viewer_dict["data"]["viewer"][
                    "flags"
                ] = f'{{"code_saving_enabled": {str(code_saving_enabled).lower()}}}'
            server_info = {
                "serverInfo": {
                    "cliVersionInfo": {
                        "max_cli_version": str(ctx.get("max_cli_version", "0.10.33"))
                    },
                    "latestLocalVersionInfo": {
                        "outOfDate": ctx.get("out_of_date", False),
                        "latestVersionString": str(ctx.get("latest_version", "0.9.42")),
                    },
                }
            }

            if ctx["empty_query"]:
                server_info["serverInfo"].pop("latestLocalVersionInfo")
            elif ctx["local_none"]:
                server_info["serverInfo"]["latestLocalVersionInfo"] = None

            viewer_dict["data"].update(server_info)

            return json.dumps(viewer_dict)

        if "query ProbeServerCapabilities" in body["query"]:
            if ctx["empty_query"]:
                return json.dumps(
                    {
                        "data": {
                            "QueryType": {
                                "fields": [
                                    {"name": "serverInfo"},
                                ]
                            },
                            "ServerInfoType": {
                                "fields": [
                                    {"name": "cliVersionInfo"},
                                    {"name": "exposesExplicitRunQueueAckPath"},
                                ]
                            },
                        }
                    }
                )

            return json.dumps(
                {
                    "data": {
                        "QueryType": {
                            "fields": [
                                {"name": "serverInfo"},
                            ]
                        },
                        "ServerInfoType": {
                            "fields": [
                                {"name": "cliVersionInfo"},
                                {"name": "latestLocalVersionInfo"},
                                {"name": "exposesExplicitRunQueueAckPath"},
                            ]
                        },
                    }
                }
            )

        if "query ProbeServerUseArtifactInput" in body["query"]:
            return json.dumps(
                {
                    "data": {
                        "UseArtifactInputInfoType": {
                            "inputFields": [
                                {"name": "entityName"},
                                {"name": "projectName"},
                                {"name": "runName"},
                                {"name": "artifactID"},
                                {"name": "usedAs"},
                                {"name": "clientMutationId"},
                            ]
                        },
                    }
                }
            )

        if "query Sweep(" in body["query"] or "query SweepWithRuns(" in body["query"]:
            return json.dumps(
                {
                    "data": {
                        "project": {
                            "sweep": {
                                "id": "1234",
                                "name": "fun-sweep-10",
                                "state": "running",
                                "bestLoss": 0.33,
                                "config": yaml.dump(
                                    {
                                        "controller": {"type": "local"},
                                        "method": "random",
                                        "parameters": {
                                            "param1": {
                                                "values": [1, 2, 3],
                                                "distribution": "categorical",
                                            },
                                            "param2": {
                                                "values": [1, 2, 3],
                                                "distribution": "categorical",
                                            },
                                        },
                                        "program": "train-dummy.py",
                                    }
                                ),
                                "createdAt": datetime.now().isoformat(),
                                "heartbeatAt": datetime.now().isoformat(),
                                "updatedAt": datetime.now().isoformat(),
                                "earlyStopJobRunning": False,
                                "controller": None,
                                "scheduler": None,
                                "runs": paginated(run(ctx), ctx),
                            }
                        }
                    }
                }
            )
        if "mutation UpsertSweep(" in body["query"]:
            return json.dumps(
                {
                    "data": {
                        "upsertSweep": {
                            "sweep": {
                                "name": "test",
                                "project": {
                                    "id": "1234",
                                    "name": "test",
                                    "entity": {"id": "1234", "name": "test"},
                                },
                            },
                            "configValidationWarnings": [],
                        }
                    }
                }
            )
        if "mutation CreateAgent(" in body["query"]:
            return json.dumps(
                {
                    "data": {
                        "createAgent": {
                            "agent": {
                                "id": "mock-server-agent-93xy",
                            }
                        }
                    }
                }
            )
        if "mutation Heartbeat(" in body["query"]:
            new_run_needed = body["variables"]["runState"] == "{}"
            if new_run_needed:
                ctx["n_sweep_runs"] += 1
            return json.dumps(
                {
                    "data": {
                        "agentHeartbeat": {
                            "agent": {
                                "id": "mock-server-agent-93xy",
                            },
                            "commands": (
                                json.dumps(
                                    [
                                        {
                                            "type": "run",
                                            "run_id": f"mocker-sweep-run-x9{ctx['n_sweep_runs']}",
                                            "args": {
                                                "a": {"value": ctx["n_sweep_runs"]}
                                            },
                                        }
                                    ]
                                )
                                if ctx["n_sweep_runs"] <= 4
                                else json.dumps([{"type": "exit"}])
                            )
                            if new_run_needed
                            else "[]",
                        }
                    }
                }
            )
        if "mutation UpsertBucket(" in body["query"]:
            run_id_default = "abc123"
            run_id = body["variables"].get("name", run_id_default)
            run_num = len(ctx["runs"])
            inserted = run_id not in ctx["runs"]
            if inserted:
                ctx["run_ids"].append(run_id)
            run_ctx = ctx["runs"].setdefault(run_id, default_ctx())

            r = run_ctx.setdefault("run", {})
            r.setdefault("display_name", "lovely-dawn-{}".format(run_num + 32))
            r.setdefault("storage_id", "storageid{}".format(run_num))
            r.setdefault("project_name", "test")
            r.setdefault("entity_name", "mock_server_entity")

            git_remote = body["variables"].get("repo")
            git_commit = body["variables"].get("commit")
            if git_commit or git_remote:
                for c in ctx, run_ctx:
                    c.setdefault("git", {})
                    c["git"]["remote"] = git_remote
                    c["git"]["commit"] = git_commit

            for c in ctx, run_ctx:
                tags = body["variables"].get("tags")
                if tags is not None:
                    c["tags"] = tags
                notes = body["variables"].get("notes")
                if notes is not None:
                    c["notes"] = notes
                group = body["variables"].get("groupName")
                if group is not None:
                    c["group"] = group
                job_type = body["variables"].get("jobType")
                if job_type is not None:
                    c["job_type"] = job_type
                name = body["variables"].get("displayName")
                if name is not None:
                    c["name"] = name
                program = body["variables"].get("program")
                if program is not None:
                    c["program"] = program
                host = body["variables"].get("host")
                if host is not None:
                    c["host"] = host

            param_config = body["variables"].get("config")
            if param_config:
                for c in ctx, run_ctx:
                    c.setdefault("config", []).append(json.loads(param_config))

            param_summary = body["variables"].get("summaryMetrics")
            if param_summary:
                for c in ctx, run_ctx:
                    c.setdefault("summary", []).append(json.loads(param_summary))

            for c in ctx, run_ctx:
                c["upsert_bucket_count"] += 1

            # Update run context
            ctx["runs"][run_id] = run_ctx

            # support legacy tests which pass resume
            if ctx["resume"] is True:
                inserted = False

            response = {
                "data": {
                    "upsertBucket": {
                        "bucket": {
                            "id": r["storage_id"],
                            "name": run_id,
                            "displayName": r["display_name"],
                            "project": {
                                "name": r["project_name"],
                                "entity": {"name": r["entity_name"]},
                            },
                        },
                        "inserted": inserted,
                    }
                }
            }
            if "mocker-sweep-run-x9" in body["variables"].get("name", ""):
                response["data"]["upsertBucket"]["bucket"][
                    "sweepName"
                ] = "test-sweep-id"
            return json.dumps(response)
        if "mutation DeleteRun(" in body["query"]:
            return json.dumps({"data": {}})
        if "mutation CreateAnonymousApiKey " in body["query"]:
            return json.dumps(
                {
                    "data": {
                        "createAnonymousEntity": {"apiKey": {"name": "ANONYMOOSE" * 4}}
                    }
                }
            )
        if "mutation DeleteFiles(" in body["query"]:
            return json.dumps({"data": {"deleteFiles": {"success": True}}})
        if "mutation PrepareFiles(" in body["query"]:
            nodes = []
            for i, file_spec in enumerate(body["variables"]["fileSpecs"]):
                url = base_url + "/storage?file=%s" % file_spec["name"]
                nodes.append(
                    {
                        "node": {
                            "id": str(i),
                            "name": file_spec["name"],
                            "displayName": file_spec["name"],
                            "digest": "null",
                            "uploadUrl": url,
                            "uploadHeaders": "",
                        }
                    }
                )
            return json.dumps({"data": {"prepareFiles": {"files": {"edges": nodes}}}})
        if "mutation LinkArtifact(" in body["query"]:
            if ART_EMU:
                return ART_EMU.link(variables=body["variables"])
        if "mutation CreateArtifact(" in body["query"]:
            if ART_EMU:
                return ART_EMU.create(variables=body["variables"])

            collection_name = body["variables"]["artifactCollectionNames"][0]
            app.logger.info("Creating artifact {}".format(collection_name))
            ctx["artifacts"] = ctx.get("artifacts", {})
            ctx["artifacts"][collection_name] = ctx["artifacts"].get(
                collection_name, []
            )
            ctx["artifacts"][collection_name].append(body["variables"])
            _id = body.get("variables", {}).get("digest", "")
            if _id != "":
                ctx.get("artifacts_by_id")[_id] = body["variables"]
            return {
                "data": {
                    "createArtifact": {
                        "artifact": artifact(
                            ctx,
                            collection_name,
                            id_override=_id,
                            state="COMMITTED"
                            if "PENDING" not in collection_name
                            else "PENDING",
                        )
                    }
                }
            }
        if "mutation DeleteArtifact(" in body["query"]:
            id = body["variables"]["artifactID"]
            delete_aliases = body["variables"]["deleteAliases"]
            art = artifact(ctx, id_override=id)
            if len(art.get("aliases", [])) and not delete_aliases:
                raise Exception("delete_aliases not set, but artifact has aliases")
            return {
                "data": {
                    "deleteArtifact": {
                        "artifact": art,
                        "success": True,
                    }
                }
            }
        if "mutation CreateArtifactManifest(" in body["query"]:
            manifest = {
                "id": 1,
                "type": "INCREMENTAL"
                if "incremental" in body.get("variables", {}).get("name", "")
                else "FULL",
                "file": {
                    "id": 1,
                    "directUrl": base_url
                    + "/storage?file=wandb_manifest.json&name={}".format(
                        body.get("variables", {}).get("name", "")
                    ),
                    "uploadUrl": base_url + "/storage?file=wandb_manifest.json",
                    "uploadHeaders": "",
                },
            }
            run_name = body.get("variables", {}).get("runName", "unknown")
            run_ctx = ctx["runs"].setdefault(run_name, default_ctx())
            for c in ctx, run_ctx:
                c["manifests_created"].append(manifest)
            return {
                "data": {
                    "createArtifactManifest": {
                        "artifactManifest": manifest,
                    }
                }
            }
        if "mutation UpdateArtifactManifest(" in body["query"]:
            manifest = {
                "id": 1,
                "type": "INCREMENTAL"
                if "incremental" in body.get("variables", {}).get("name", "")
                else "FULL",
                "file": {
                    "id": 1,
                    "directUrl": base_url
                    + "/storage?file=wandb_manifest.json&name={}".format(
                        body.get("variables", {}).get("name", "")
                    ),
                    "uploadUrl": base_url + "/storage?file=wandb_manifest.json",
                    "uploadHeaders": "",
                },
            }
            return {
                "data": {
                    "updateArtifactManifest": {
                        "artifactManifest": manifest,
                    }
                }
            }
        if "mutation CreateArtifactFiles" in body["query"]:
            if ART_EMU:
                return ART_EMU.create_files(variables=body["variables"])
            return {
                "data": {
                    "files": [
                        {
                            "node": {
                                "id": idx,
                                "name": file["name"],
                                "uploadUrl": "",
                                "uploadheaders": [],
                                "artifact": {"id": file["artifactID"]},
                            }
                            for idx, file in enumerate(
                                body["variables"]["artifactFiles"]
                            )
                        }
                    ],
                }
            }
        if "mutation CommitArtifact(" in body["query"]:
            return {
                "data": {
                    "commitArtifact": {
                        "artifact": {"id": 1, "digest": "0000===================="}
                    }
                }
            }
        if "mutation UseArtifact(" in body["query"]:
            used_name = body.get("variables", {}).get("usedAs", None)
            ctx["used_artifact_info"] = {"used_name": used_name}
            return {"data": {"useArtifact": {"artifact": artifact(ctx)}}}
        if "query ProjectArtifactType(" in body["query"]:
            return {
                "data": {
                    "project": {
                        "artifactType": {
                            "id": "1",
                            "name": "dataset",
                            "description": "",
                            "createdAt": datetime.now().isoformat(),
                        }
                    }
                }
            }
        if "query ProjectArtifacts(" in body["query"]:
            return {
                "data": {
                    "project": {
                        "artifactTypes": paginated(
                            {
                                "id": "1",
                                "name": "dataset",
                                "description": "",
                                "createdAt": datetime.now().isoformat(),
                            },
                            ctx,
                        )
                    }
                }
            }
        if "query ProjectArtifactCollections(" in body["query"]:
            return {
                "data": {
                    "project": {
                        "artifactType": {
                            "artifactSequences": paginated(
                                {
                                    "id": "1",
                                    "name": "mnist",
                                    "description": "",
                                    "createdAt": datetime.now().isoformat(),
                                },
                                ctx,
                            )
                        }
                    }
                }
            }
        if "query ArtifactCollection(" in body["query"]:
            return {
                "data": {
                    "project": {
                        "artifactType": {
                            "artifactSequence": {
                                "id": "1",
                                "name": "mnist",
                                "description": "",
                                "createdAt": datetime.now().isoformat(),
                            }
                        }
                    }
                }
            }
        # backward compatible for 0.12.10 and below
        if "query RunArtifacts(" in body["query"]:
            if "inputArtifacts" in body["query"]:
                key = "inputArtifacts"
            else:
                key = "outputArtifacts"
            artifacts = paginated(artifact(ctx), ctx)
            artifacts["totalCount"] = ctx["page_times"]
            return {"data": {"project": {"run": {key: artifacts}}}}
        if "query RunInputArtifacts(" in body["query"]:
            artifacts = paginated(artifact(ctx), ctx)
            artifacts["totalCount"] = ctx["page_times"]
            return {"data": {"project": {"run": {"inputArtifacts": artifacts}}}}
        if "query RunOutputArtifacts(" in body["query"]:
            artifacts = paginated(artifact(ctx), ctx)
            artifacts["totalCount"] = ctx["page_times"]
            return {"data": {"project": {"run": {"outputArtifacts": artifacts}}}}
        if "query Artifacts(" in body["query"]:
            version = "v%i" % ctx["page_count"]
            artifacts = paginated(artifact(ctx), ctx, {"version": version})
            artifacts["totalCount"] = ctx["page_times"]
            return {
                "data": {
                    "project": {
                        "artifactType": {
                            "artifactSequence": {
                                "name": "mnist",
                                "artifacts": artifacts,
                            }
                        }
                    }
                }
            }
        for query_name in [
            "Artifact",
            "ArtifactType",
            "ArtifactWithCurrentManifest",
            "ArtifactUsedBy",
            "ArtifactCreatedBy",
        ]:
            if f"query {query_name}(" in body["query"]:
                if ART_EMU:
                    return ART_EMU.query(
                        variables=body.get("variables", {}), query=body.get("query")
                    )
                art = artifact(
                    ctx, request_url_root=base_url, id_override="QXJ0aWZhY3Q6NTI1MDk4"
                )
                if "id" in body.get("variables", {}):
                    art = artifact(
                        ctx,
                        request_url_root=base_url,
                        id_override=body.get("variables", {}).get("id"),
                    )
                    art["artifactType"] = {"id": 1, "name": "dataset"}
                    return {"data": {"artifact": art}}
                if ctx["swappable_artifacts"] and "name" in body.get("variables", {}):
                    full_name = body.get("variables", {}).get("name", None)
                    if full_name is not None:
                        collection_name = full_name.split(":")[0]
                    art = artifact(
                        ctx,
                        collection_name=collection_name,
                        request_url_root=base_url,
                    )
                # code artifacts use source-RUNID names, we return the code type
                art["artifactType"] = {"id": 2, "name": "code"}
                if "source" not in body["variables"]["name"]:
                    art["artifactType"] = {"id": 1, "name": "dataset"}
                if "logged_table" in body["variables"]["name"]:
                    art["artifactType"] = {"id": 3, "name": "run_table"}
                if "run-" in body["variables"]["name"]:
                    art["artifactType"] = {"id": 4, "name": "run_table"}
                if "wb_validation_data" in body["variables"]["name"]:
                    art["artifactType"] = {"id": 4, "name": "validation_dataset"}
                return {"data": {"project": {"artifact": art}}}
        if "query ArtifactManifest(" in body["query"]:
            art = artifact(ctx)
            art["currentManifest"] = {
                "id": 1,
                "file": {
                    "id": 1,
                    "directUrl": base_url
                    + "/storage?file=wandb_manifest.json&name={}".format(
                        body.get("variables", {}).get("name", "")
                    ),
                },
            }
            return {"data": {"project": {"artifact": art}}}
        # Project() is backward compatible for 0.12.10 and below
        if ("query Project(" in body["query"] and "runQueues" in body["query"]) or (
            "query ProjectRunQueues(" in body["query"] and "runQueues" in body["query"]
        ):
            if ctx["run_queues_return_default"]:
                return json.dumps(
                    {
                        "data": {
                            "project": {
                                "runQueues": [
                                    {
                                        "id": 1,
                                        "name": "default",
                                        "createdBy": "mock_server_entity",
                                        "access": "PROJECT",
                                    }
                                ]
                            }
                        }
                    }
                )
            else:
                return json.dumps({"data": {"project": {"runQueues": []}}})

        if "query GetRunQueueItem" in body["query"]:
            ctx["run_queue_item_check_count"] += 1
            if ctx["run_queue_item_check_count"] > 1:
                return json.dumps(
                    {
                        "data": {
                            "project": {
                                "runQueue": {
                                    "runQueueItems": {
                                        "edges": [
                                            {
                                                "node": {
                                                    "id": "test",
                                                    "resultingRunId": "test",
                                                }
                                            }
                                        ]
                                    }
                                }
                            }
                        }
                    }
                )
            else:
                return json.dumps(
                    {
                        "data": {
                            "project": {
                                "runQueue": {
                                    "runQueueItems": {
                                        "edges": [
                                            {
                                                "node": {
                                                    "id": "test",
                                                    "resultingRunId": None,
                                                }
                                            }
                                        ]
                                    }
                                }
                            }
                        }
                    }
                )
        if "mutation createRunQueue" in body["query"]:
            if not ctx["successfully_create_default_queue"]:
                return json.dumps(
                    {"data": {"createRunQueue": {"success": False, "queueID": None}}}
                )
            ctx["run_queues_return_default"] = True
            return json.dumps(
                {"data": {"createRunQueue": {"success": True, "queueID": 1}}}
            )
        if "mutation popFromRunQueue" in body["query"]:
            if ctx["num_popped"] != 0:
                return json.dumps({"data": {"popFromRunQueue": None}})
            ctx["num_popped"] += 1
            if ctx["invalid_launch_spec_project"]:
                return json.dumps(
                    {
                        "data": {
                            "popFromRunQueue": {
                                "runQueueItemId": 1,
                                "runSpec": {
                                    "uri": "https://wandb.ai/mock_server_entity/test_project/runs/1",
                                    "project": "test_project2",
                                    "entity": "mock_server_entity",
                                    "resource": "local",
                                },
                            }
                        }
                    }
                )
            return json.dumps(
                {
                    "data": {
                        "popFromRunQueue": {
                            "runQueueItemId": 1,
                            "runSpec": {
                                "uri": "https://wandb.ai/mock_server_entity/test_project/runs/1",
                                "project": "test_project",
                                "entity": "mock_server_entity",
                                "resource": "local",
                            },
                        }
                    }
                }
            )
        if "mutation pushToRunQueue" in body["query"]:
            if ctx["run_queues"].get(body["variables"]["queueID"]):
                ctx["run_queues"][body["variables"]["queueID"]].append(
                    body["variables"]["queueID"]
                )
            else:
                ctx["run_queues"][body["variables"]["queueID"]] = [
                    body["variables"]["queueID"]
                ]
            return json.dumps({"data": {"pushToRunQueue": {"runQueueItemId": 1}}})
        if "mutation ackRunQueueItem" in body["query"]:
            ctx["num_acked"] += 1
            return json.dumps({"data": {"ackRunQueueItem": {"success": True}}})
        if "query ClientIDMapping(" in body["query"]:
            return {"data": {"clientIDMapping": {"serverID": "QXJ0aWZhY3Q6NTI1MDk4"}}}
        # Admin apis
        if "mutation DeleteApiKey" in body["query"]:
            return {"data": {"deleteApiKey": {"success": True}}}
        if "mutation GenerateApiKey" in body["query"]:
            return {
                "data": {"generateApiKey": {"apiKey": {"id": "XXX", "name": "Y" * 40}}}
            }
        if "mutation DeleteInvite" in body["query"]:
            return {"data": {"deleteInvite": {"success": True}}}
        if "mutation CreateInvite" in body["query"]:
            return {"data": {"createInvite": {"invite": {"id": "XXX"}}}}
        if "mutation CreateServiceAccount" in body["query"]:
            return {"data": {"createServiceAccount": {"user": {"id": "XXX"}}}}
        if "mutation CreateTeam" in body["query"]:
            return {
                "data": {
                    "createTeam": {
                        "entity": {"id": "XXX", "name": body["variables"]["teamName"]}
                    }
                }
            }
        if "mutation NotifyScriptableRunAlert" in body["query"]:
            avars = body.get("variables", {})
            run_name = avars.get("runName", "unknown")
            adict = dict(
                title=avars["title"], text=avars["text"], severity=avars["severity"]
            )
            atime = avars.get("waitDuration")
            if atime is not None:
                adict["wait"] = atime
            run_ctx = ctx["runs"].setdefault(run_name, default_ctx())
            for c in ctx, run_ctx:
                c["alerts"].append(adict)
            return {"data": {"notifyScriptableRunAlert": {"success": True}}}
        if "query SearchUsers" in body["query"]:

            return {
                "data": {
                    "users": {
                        "edges": [
                            {
                                "node": {
                                    "id": "XXX",
                                    "email": body["variables"]["query"],
                                    "apiKeys": {
                                        "edges": [
                                            {"node": {"id": "YYY", "name": "Y" * 40}}
                                        ]
                                    },
                                    "teams": {
                                        "edges": [
                                            {"node": {"id": "TTT", "name": "test"}}
                                        ]
                                    },
                                }
                            }
                        ]
                        * ctx["num_search_users"]
                    }
                }
            }
        if "query Entity(" in body["query"]:
            return {
                "data": {
                    "entity": {
                        "id": "XXX",
                        "members": [
                            {
                                "id": "YYY",
                                "name": "test",
                                "accountType": "MEMBER",
                                "apiKey": None,
                            },
                            {
                                "id": "SSS",
                                "name": "Service account",
                                "accountType": "SERVICE",
                                "apiKey": "Y" * 40,
                            },
                        ],
                    }
                }
            }
        if "stopped" in body["query"]:
            return json.dumps(
                {
                    "data": {
                        "Model": {
                            "project": {"run": {"stopped": ctx.get("stopped", False)}}
                        }
                    }
                }
            )
        if "mutation createLaunchAgent(" in body["query"]:
            agent_id = len(ctx["launch_agents"].keys())
            ctx["launch_agents"][agent_id] = "POLLING"
            return json.dumps(
                {
                    "data": {
                        "createLaunchAgent": {
                            "success": True,
                            "launchAgentId": agent_id,
                        }
                    }
                }
            )
        if "mutation updateLaunchAgent(" in body["query"]:
            if ctx["launch_agent_update_fail"]:
                return json.dumps({"data": {"updateLaunchAgent": {"success": False}}})
            status = body["variables"]["agentStatus"]
            agent_id = body["variables"]["agentId"]
            ctx["launch_agents"][agent_id] = status
            return json.dumps({"data": {"updateLaunchAgent": {"success": True}}})
        if "query LaunchAgentIntrospection" in body["query"]:
            if ctx["gorilla_supports_launch_agents"]:
                return json.dumps(
                    {"data": {"LaunchAgentType": {"name": "LaunchAgent"}}}
                )
            else:
                return json.dumps({"data": {}})
        if "query LaunchAgent" in body["query"]:
            if ctx["gorilla_supports_launch_agents"]:
                return json.dumps(
                    {
                        "data": {
                            "launchAgent": {
                                "name": "test_agent",
                                "stopPolling": ctx["stop_launch_agent"],
                            }
                        }
                    }
                )
            else:
                return json.dumps({"data": {}})

        if "query GetSweeps" in body["query"]:
            if body["variables"]["project"] == "testnosweeps":
                return {"data": {"project": {"totalSweeps": 0, "sweeps": {}}}}
            return {
                "data": {
                    "project": {
                        "totalSweeps": 1,
                        "sweeps": {
                            "edges": [
                                {
                                    "node": {
                                        "id": "testdatabaseid",
                                        "name": "testid",
                                        "bestLoss": 0.5,
                                        "config": yaml.dump({"name": "testname"}),
                                    }
                                }
                            ]
                        },
                    }
                }
            }

        print("MISSING QUERY, add me to tests/mock_server.py", body["query"])
        error = {"message": "Not implemented in tests/mock_server.py", "body": body}
        return json.dumps({"errors": [error]})

    @app.route("/storage", methods=["PUT", "GET"])
    @app.route("/storage/<path:extra>", methods=["PUT", "GET"])
    def storage(extra=None):
        ctx = get_ctx()
        if "fail_storage_times" in ctx:
            if ctx["fail_storage_count"] < ctx["fail_storage_times"]:
                ctx["fail_storage_count"] += 1
                return json.dumps({"errors": ["Server down"]}), 500
        file = request.args.get("file")
        _id = request.args.get("id", "")
        run = request.args.get("run", "unknown")
        # Grab the run from the url for azure uploads
        if extra and run == "unknown":
            run = extra.split("/")[-2]
        ctx["storage"] = ctx.get("storage", {})
        ctx["storage"][run] = ctx["storage"].get(run, [])
        ctx["storage"][run].append(request.args.get("file"))
        size = ctx["files"].get(request.args.get("file"))
        if request.method == "GET" and size:
            return os.urandom(size), 200
        # make sure to read the data
        request.get_data(as_text=True)
        # We need to bomb out before storing the file as uploaded for tests
        inject = InjectRequestsParse(ctx).find(request=request)
        if inject:
            if inject.response:
                response = inject.response
            if inject.http_status:
                # print("INJECT", inject, inject.http_status)
                raise HttpException(
                    {"code": 500, "message": "some error"},
                    status_code=inject.http_status,
                )

        run_ctx = ctx["runs"].setdefault(run, default_ctx())
        for c in ctx, run_ctx:
            if extra:
                file = extra.split("/")[-1]
            else:
                file = request.args.get("file", "UNKNOWN_STORAGE_FILE_PUT")
            c["file_names"].append(file)

        if request.method == "PUT":
            for c in ctx, run_ctx:
                c["file_bytes"].setdefault(file, 0)
                c["file_bytes"][file] += request.content_length
        if ART_EMU:
            return ART_EMU.storage(request=request)
        if file == "wandb_manifest.json":
            if _id in ctx.get("artifacts_by_id"):
                art = ctx["artifacts_by_id"][_id]
                if "-validation_predictions" in art["artifactCollectionNames"][0]:
                    return {
                        "version": 1,
                        "storagePolicy": "wandb-storage-policy-v1",
                        "storagePolicyConfig": {},
                        "contents": {
                            "validation_predictions.table.json": {
                                "digest": "3aaaaaaaaaaaaaaaaaaaaa==",
                                "size": 81299,
                            }
                        },
                    }
                if "wb_validation_data" in art["artifactCollectionNames"][0]:
                    return {
                        "version": 1,
                        "storagePolicy": "wandb-storage-policy-v1",
                        "storagePolicyConfig": {},
                        "contents": {
                            "validation_data.table.json": {
                                "digest": "3aaaaaaaaaaaaaaaaaaaaa==",
                                "size": 81299,
                            },
                            "media/tables/5aac4cea496fd061e813.table.json": {
                                "digest": "3aaaaaaaaaaaaaaaaaaaaa==",
                                "size": 81299,
                            },
                        },
                    }
            if request.args.get("name") == "my-test_reference_download:latest":
                return {
                    "version": 1,
                    "storagePolicy": "wandb-storage-policy-v1",
                    "storagePolicyConfig": {},
                    "contents": {
                        "StarWars3.wav": {
                            "digest": "a90eb05f7aef652b3bdd957c67b7213a",
                            "size": 81299,
                            "ref": "https://wandb-artifacts-refs-public-test.s3-us-west-2.amazonaws.com/StarWars3.wav",
                        },
                        "file1.txt": {
                            "digest": "0000====================",
                            "size": 81299,
                        },
                    },
                }
            elif (
                _id == "bb8043da7d78ff168a695cff097897d2"
                or _id == "ad4d74ac0e4167c6cf4aaad9d59b9b44"
            ):
                return {
                    "version": 1,
                    "storagePolicy": "wandb-storage-policy-v1",
                    "storagePolicyConfig": {},
                    "contents": {
                        "t1.table.json": {
                            "digest": "3aaaaaaaaaaaaaaaaaaaaa==",
                            "size": 81299,
                        }
                    },
                }
            elif _id == "27c102831476c6ff7ce53c266c937612":
                return {
                    "version": 1,
                    "storagePolicy": "wandb-storage-policy-v1",
                    "storagePolicyConfig": {},
                    "contents": {
                        "logged_table.table.json": {
                            "digest": "3aaaaaaaaaaaaaaaaaaaaa==",
                            "size": 81299,
                        }
                    },
                }
            elif _id == "b9a598178557aed1d89bd93ec0db989b":
                return {
                    "version": 1,
                    "storagePolicy": "wandb-storage-policy-v1",
                    "storagePolicyConfig": {},
                    "contents": {
                        "logged_table_2.table.json": {
                            "digest": "3aaaaaaaaaaaaaaaaaaaaa==",
                            "size": 81299,
                        }
                    },
                }
            elif _id == "e6954815d2beb5841b3dabf7cf455c30":
                return {
                    "version": 1,
                    "storagePolicy": "wandb-storage-policy-v1",
                    "storagePolicyConfig": {},
                    "contents": {
                        "logged_table.partitioned-table.json": {
                            "digest": "3aaaaaaaaaaaaaaaaaaaaa==",
                            "size": 81299,
                        }
                    },
                }
            elif _id == "0eec13efd400546f58a4530de62ed07a":
                return {
                    "version": 1,
                    "storagePolicy": "wandb-storage-policy-v1",
                    "storagePolicyConfig": {},
                    "contents": {
                        "jt.joined-table.json": {
                            "digest": "3aaaaaaaaaaaaaaaaaaaaa==",
                            "size": 81299,
                        }
                    },
                }
            elif _id in [
                "2d9a7e0aa8407f0730e19e5bc55c3a45",
                "c541de19b18331a4a33b282fc9d42510",
                "6f3d6ed5417d2955afbc73bff0ed1609",
                "7d797e62834a7d72538529e91ed958e2",
                "03d3e221fd4da6c5fccb1fbd75fe475e",
                "464aa7e0d7c3f8230e3fe5f10464a2e6",
                "8ef51aeabcfcd89b719822de64f6a8bf",
            ]:
                return {
                    "version": 1,
                    "storagePolicy": "wandb-storage-policy-v1",
                    "storagePolicyConfig": {},
                    "contents": {
                        "validation_data.table.json": {
                            "digest": "3aaaaaaaaaaaaaaaaaaaaa==",
                            "size": 81299,
                        },
                        "media/tables/e14239fe.table.json": {
                            "digest": "3aaaaaaaaaaaaaaaaaaaaa==",
                            "size": 81299,
                        },
                    },
                }
            elif (
                len(ctx.get("graphql", [])) >= 3
                and ctx["graphql"][2].get("variables", {}).get("name", "") == "dummy:v0"
            ) or request.args.get("name") == "dummy:v0":
                return {
                    "version": 1,
                    "storagePolicy": "wandb-storage-policy-v1",
                    "storagePolicyConfig": {},
                    "contents": {
                        "dataset.partitioned-table.json": {
                            "digest": "0aaaaaaaaaaaaaaaaaaaaa==",
                            "size": 81299,
                        },
                        "parts/1.table.json": {
                            "digest": "1aaaaaaaaaaaaaaaaaaaaa==",
                            "size": 81299,
                        },
                        "t.table.json": {
                            "digest": "2aaaaaaaaaaaaaaaaaaaaa==",
                            "size": 123,
                        },
                    },
                }
            elif _id == "e04169452d5584146eb7ebb405647cc8":
                return {
                    "version": 1,
                    "storagePolicy": "wandb-storage-policy-v1",
                    "storagePolicyConfig": {},
                    "contents": {
                        "results_df.table.json": {
                            "digest": "0aaaaaaaaaaaaaaaaaaaaa==",
                            "size": 363,
                        },
                    },
                }
            else:
                return {
                    "version": 1,
                    "storagePolicy": "wandb-storage-policy-v1",
                    "storagePolicyConfig": {},
                    "contents": {
                        "digits.h5": {
                            "digest": "TeSJ4xxXg0ohuL5xEdq2Ew==",
                            "size": 81299,
                        },
                    },
                }
        elif file == "wandb-metadata.json":
            if ctx["return_jupyter_in_run_info"]:
                code_path = "one_cell.ipynb"
            else:
                code_path = "train.py"
            result = {
                "docker": "test/docker",
                "program": "train.py",
                "codePath": code_path,
                "args": ["--test", "foo"],
                "git": ctx.get("git", {}),
            }
            if ctx["run_cuda_version"]:
                result["cuda"] = ctx["run_cuda_version"]
            return result
        elif file == "requirements.txt":
            return "numpy==1.19.5\n"
        elif file == "diff.patch":
            # TODO: make sure the patch is valid for windows as well,
            # and un skip the test in test_cli.py
            return """
diff --git a/patch.txt b/patch.txt
index 30d74d2..9a2c773 100644
--- a/patch.txt
+++ b/patch.txt
@@ -1 +1 @@
-test
\ No newline at end of file
+testing
\ No newline at end of file
"""
        # emulate azure when we're receving requests from them
        if extra is not None:
            return "", 201
        return "", 200

    @app.route("/artifacts/<entity>/<digest>", methods=["GET", "POST"])
    def artifact_file(entity, digest):
        if ART_EMU:
            return ART_EMU.file(entity=entity, digest=digest)
        if entity == "entity" or entity == "mock_server_entity":
            if (
                digest == "d1a69a69a69a69a69a69a69a69a69a69"
            ):  # "dataset.partitioned-table.json"
                return (
                    json.dumps({"_type": "partitioned-table", "parts_path": "parts"}),
                    200,
                )
            elif digest == "d5a69a69a69a69a69a69a69a69a69a69":  # "parts/1.table.json"
                return (
                    json.dumps(
                        {
                            "_type": "table",
                            "column_types": {
                                "params": {
                                    "type_map": {
                                        "A": {
                                            "params": {
                                                "allowed_types": [
                                                    {"wb_type": "none"},
                                                    {"wb_type": "number"},
                                                ]
                                            },
                                            "wb_type": "union",
                                        },
                                        "B": {
                                            "params": {
                                                "allowed_types": [
                                                    {"wb_type": "none"},
                                                    {"wb_type": "number"},
                                                ]
                                            },
                                            "wb_type": "union",
                                        },
                                        "C": {
                                            "params": {
                                                "allowed_types": [
                                                    {"wb_type": "none"},
                                                    {"wb_type": "number"},
                                                ]
                                            },
                                            "wb_type": "union",
                                        },
                                    }
                                },
                                "wb_type": "dictionary",
                            },
                            "columns": ["A", "B", "C"],
                            "data": [[0, 0, 1]],
                            "ncols": 3,
                            "nrows": 1,
                        }
                    ),
                    200,
                )
            elif digest == "d9a69a69a69a69a69a69a69a69a69a69":  # "t.table.json"
                return (
                    json.dumps(
                        {
                            "_type": "table",
                            "column_types": {
                                "params": {"type_map": {}},
                                "wb_type": "dictionary",
                            },
                            "columns": [],
                            "data": [],
                            "ncols": 0,
                            "nrows": 0,
                        }
                    ),
                    200,
                )

        if digest == "dda69a69a69a69a69a69a69a69a69a69":
            return (
                json.dumps({"_type": "table-file", "columns": [], "data": []}),
                200,
            )

        return "ARTIFACT %s" % digest, 200

    @app.route("/files/<entity>/<project>/<run>/file_stream", methods=["POST"])
    @snoop.relay
    def file_stream(entity, project, run):
        ctx = get_ctx()
        run_ctx = get_run_ctx(run)
        for c in ctx, run_ctx:
            c["file_stream"] = c.get("file_stream", [])
            c["file_stream"].append(request.get_json())
        response = json.dumps({"exitcode": None, "limits": {}})

        inject = InjectRequestsParse(ctx).find(request=request)
        if inject:
            if inject.response:
                response = inject.response
            if inject.http_status:
                # print("INJECT", inject, inject.http_status)
                raise HttpException("some error", status_code=inject.http_status)
        return response

    @app.route("/api/v1/namespaces/default/pods/test")
    def k8s_pod():
        ctx = get_ctx()
        image_id = b"docker-pullable://test@sha256:1234"
        ms = b'{"status":{"containerStatuses":[{"imageID":"%s"}]}}' % image_id
        if ctx.get("k8s"):
            return ms, 200
        else:
            return b"", 500

    @app.route("/api/sessions")
    def jupyter_sessions():
        return json.dumps(
            [
                {
                    "kernel": {"id": "12345"},
                    "notebook": {"path": "test.ipynb", "name": "test.ipynb"},
                }
            ]
        )

    @app.route("/wandb_url", methods=["PUT"])
    def spell_url():
        ctx = get_ctx()
        ctx["spell_data"] = request.get_json()
        return json.dumps({"success": True})

    @app.route("/pypi/<library>/json")
    def pypi(library):
        version = getattr(wandb, "__hack_pypi_latest_version__", wandb.__version__)
        return json.dumps(
            {
                "info": {"version": version},
                "releases": {
                    "88.1.2rc2": [],
                    "88.1.2rc12": [],
                    "88.1.2rc3": [],
                    "88.1.2rc4": [],
                    "0.11.0": [],
                    "0.10.32": [],
                    "0.10.31": [],
                    "0.10.30": [],
                    "0.0.8rc6": [],
                    "0.0.8rc2": [],
                    "0.0.8rc3": [],
                    "0.0.8rc8": [],
                    "0.0.2": [{"yanked": True}],
                    "0.0.3": [{"yanked": True, "yanked_reason": "just cuz"}],
                    "0.0.7": [],
                    "0.0.5": [],
                    "0.0.6": [],
                },
            }
        )

    @app.route("/api/5288891/store/", methods=["POST"])
    def sentry_put():
        ctx = get_ctx()
        data = request.get_data()
        data = gzip.decompress(data)
        data = str(data, "utf-8")
        data = json.loads(data)
        ctx["sentry_events"].append(data)
        return ""

    @app.errorhandler(404)
    def page_not_found(e):
        print("Got request to: %s (%s)" % (request.url, request.method))
        return "Not Found", 404

    return app


RE_DATETIME = re.compile("^(?P<date>\d+-\d+-\d+T\d+:\d+:\d+[.]\d+\s)(?P<rest>.*)$")


def strip_datetime(s):
    # 2021-09-18T17:28:07.059270
    m = RE_DATETIME.match(s)
    if m:
        return m.group("rest")
    return s


class ParseCTX(object):
    def __init__(self, ctx, run_id=None):
        self._ctx = ctx["runs"][run_id] if run_id else ctx
        self._run_id = run_id

    def get_filestream_file_updates(self):
        data = {}
        file_stream_updates = self._ctx.get("file_stream", [])
        for update in file_stream_updates:
            files = update.get("files")
            if not files:
                continue
            for k, v in six.iteritems(files):
                data.setdefault(k, []).append(v)
        return data

    def get_filestream_file_items(self):
        data = {}
        fs_file_updates = self.get_filestream_file_updates()
        for k, v in six.iteritems(fs_file_updates):
            l = []
            for d in v:
                offset = d.get("offset")
                content = d.get("content")
                assert offset is not None
                assert content is not None
                # this check isnt valid right now.
                # TODO: lets just assume it is fine, look into this later
                # assert offset == 0 or offset == len(l), (k, v, l, d)
                if not offset:
                    l = []
                if k == "output.log":
                    lines = content
                else:
                    lines = map(json.loads, content)
                l.extend(lines)
            data[k] = l
        return data

    @property
    def run_ids(self):
        return self._ctx.get("run_ids", [])

    @property
    def file_names(self):
        return self._ctx.get("file_names", [])

    @property
    def files(self):
        files_sizes = self._ctx.get("file_bytes", {})
        files_dict = {}
        for fname, size in files_sizes.items():
            files_dict.setdefault(fname, {})
            files_dict[fname]["size"] = size
        return files_dict

    @property
    def dropped_chunks(self):
        return self._ctx.get("file_stream", [{"dropped": 0}])[-1]["dropped"]

    @property
    def summary_raw(self):
        fs_files = self.get_filestream_file_items()
        summary = fs_files.get("wandb-summary.json", [{}])[-1]
        return summary

    @property
    def summary_user(self):
        return {k: v for k, v in self.summary_raw.items() if not k.startswith("_")}

    @property
    def summary(self):
        # TODO: move this to config_user eventually
        return {k: v for k, v in self.summary_raw.items() if k != "_wandb"}

    @property
    def summary_wandb(self):
        return self.summary_raw.get("_wandb", {})

    @property
    def history(self):
        fs_files = self.get_filestream_file_items()
        history = fs_files.get("wandb-history.jsonl")
        return history

    @property
    def output(self):
        fs_files = self.get_filestream_file_items()
        output_items = fs_files.get("output.log", [])
        err_prefix = "ERROR "
        stdout_items = []
        stderr_items = []
        for item in output_items:
            if item.startswith(err_prefix):
                err_item = item[len(err_prefix) :]
                stderr_items.append(err_item)
            else:
                stdout_items.append(item)
        stdout = "".join(stdout_items)
        stderr = "".join(stderr_items)
        stdout_lines = stdout.splitlines()
        stderr_lines = stderr.splitlines()
        stdout = list(map(strip_datetime, stdout_lines))
        stderr = list(map(strip_datetime, stderr_lines))
        return dict(stdout=stdout, stderr=stderr)

    @property
    def exit_code(self):
        exit_code = None
        fs_list = self._ctx.get("file_stream")
        if fs_list:
            exit_code = fs_list[-1].get("exitcode")
        return exit_code

    @property
    def run_id(self):
        return self._run_id

    @property
    def git(self):
        git_info = self._ctx.get("git")
        return git_info or dict(commit=None, remote=None)

    @property
    def config_raw(self):
        return self._ctx["config"][-1]

    @property
    def config_user(self):
        return {
            k: v["value"] for k, v in self.config_raw.items() if not k.startswith("_")
        }

    @property
    def config(self):
        # TODO: move this to config_user eventually
        return self.config_raw

    @property
    def config_wandb(self):
        return self.config.get("_wandb", {}).get("value", {})

    @property
    def telemetry(self):
        return self.config.get("_wandb", {}).get("value", {}).get("t", {})

    @property
    def metrics(self):
        return self.config.get("_wandb", {}).get("value", {}).get("m", {})

    @property
    def manifests_created(self):
        return self._ctx.get("manifests_created") or []

    @property
    def manifests_created_ids(self):
        return [m["id"] for m in self.manifests_created]

    @property
    def artifacts(self):
        return self._ctx.get("artifacts_created") or {}

    @property
    def portfolio_links(self):
        return self._ctx.get("portfolio_links") or {}

    @property
    def tags(self):
        return self._ctx.get("tags") or []

    @property
    def notes(self):
        return self._ctx.get("notes") or ""

    @property
    def group(self):
        return self._ctx.get("group") or ""

    @property
    def job_type(self):
        return self._ctx.get("job_type") or ""

    @property
    def name(self):
        return self._ctx.get("name") or ""

    @property
    def program(self):
        return self._ctx.get("program") or ""

    @property
    def host(self):
        return self._ctx.get("host") or ""

    @property
    def alerts(self):
        return self._ctx.get("alerts") or []

    @property
    def sentry_events(self):
        return self._ctx.get("sentry_events") or []

    def _debug(self):
        if not self._run_id:
            items = {"run_ids": "run_ids", "artifacts": "artifacts"}
        else:
            items = {
                "config": "config_user",
                "summary": "summary_user",
                "exit_code": "exit_code",
                "telemetry": "telemetry",
            }
        d = {}
        for k, v in items.items():
            d[k] = getattr(self, v)
        return d


if __name__ == "__main__":
    use_yea = "--yea" in sys.argv[1:]
    load_modules(use_yea=use_yea)

    app = create_app()
    app.logger.setLevel(logging.INFO)

    # allow caller to bind to a specific hostaddr
    mockserver_bind = os.environ.get("MOCKSERVER_BIND")
    kwargs = {}
    if mockserver_bind:
        kwargs["host"] = mockserver_bind

    app.run(debug=False, port=int(os.environ.get("PORT", 8547)), **kwargs)
