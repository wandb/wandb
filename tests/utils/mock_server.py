"""Mock Server for simple calls the cli and public api make"""

from flask import Flask, request, g, jsonify
import os
import sys
from datetime import datetime, timedelta
import json
import yaml
import six

# HACK: restore first two entries of sys path after wandb load
save_path = sys.path[:2]
import wandb

sys.path[0:0] = save_path
import logging
from six.moves import urllib
import threading

from tests.utils.mock_requests import RequestsMock, InjectRequestsParse

# from yea_wandb.mock_requests import RequestsMock, InjectRequestsParse


def default_ctx():
    return {
        "fail_graphql_count": 0,  # used via "fail_graphql_times"
        "fail_storage_count": 0,  # used via "fail_storage_times"
        "rate_limited_count": 0,  # used via "rate_limited_times"
        "page_count": 0,
        "page_times": 2,
        "requested_file": "weights.h5",
        "current_run": None,
        "files": {},
        "k8s": False,
        "resume": None,
        "file_bytes": {},
        "manifests_created": [],
        "artifacts_by_id": {},
        "upsert_bucket_count": 0,
        "max_cli_version": "0.10.33",
        "runs": {},
        "run_ids": [],
        "file_names": [],
    }


def mock_server(mocker):
    ctx = default_ctx()
    app = create_app(ctx)
    mock = RequestsMock(app, ctx)
    # We mock out all requests libraries, couldn't find a way to mock the core lib
    mocker.patch("wandb.apis.client.requests", mock)
    mocker.patch("wandb.wandb_sdk.internal.file_stream.requests", mock)
    mocker.patch("wandb.wandb_sdk.internal.internal_api.requests", mock)
    mocker.patch("wandb.wandb_sdk.internal.update.requests", mock)
    mocker.patch("wandb.wandb_sdk.internal.sender.requests", mock)
    mocker.patch("wandb.apis.internal_runqueue.requests", mock)
    mocker.patch("wandb.apis.public.requests", mock)
    mocker.patch("wandb.util.requests", mock)
    mocker.patch("wandb.wandb_sdk.wandb_artifacts.requests", mock)
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
            "edges": [{"node": fileNode,}]
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
        "artifactSequence": {"name": collection_name,},
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
                        "directUrl": base_url + "/storage?file=" + name,
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


def create_app(user_ctx=None):
    app = Flask(__name__)
    # When starting in live mode, user_ctx is a fancy object
    if isinstance(user_ctx, dict):
        with app.app_context():
            set_ctx(user_ctx)

    @app.teardown_appcontext
    def persist_ctx(exc):
        if "ctx" in g:
            CTX.persist(g.ctx)

    @app.errorhandler(HttpException)
    def handle_http_exception(error):
        response = jsonify(error.to_dict())
        response.status_code = error.status_code
        return response

    @app.route("/ctx", methods=["GET", "PUT", "DELETE"])
    def update_ctx():
        """Updating context for live_mock_server"""
        ctx = get_ctx()
        body = request.get_json()
        if request.method == "GET":
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
        body = request.get_json()
        app.logger.info("graphql post body: %s", body)
        if body["variables"].get("run"):
            ctx["current_run"] = body["variables"]["run"]

        if body["variables"].get("files"):
            requested_file = body["variables"]["files"][0]
            ctx["requested_file"] = requested_file
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
                                    "uploadHeaders": [],
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
                                    "summaryMetrics": '{"acc": 10, "best_val_loss": 0.5}',
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
        if "query Run(" in body["query"]:
            return json.dumps({"data": {"project": {"run": run(ctx)}}})
        if "query Model(" in body["query"]:
            if "project(" in body["query"]:
                project_field_name = "project"
                run_field_name = "run"
            else:
                project_field_name = "model"
                run_field_name = "bucket"
            if "commit" in body["query"]:
                run_config = _bucket_config(ctx)
            else:
                run_config = run(ctx)
            return json.dumps(
                {"data": {project_field_name: {run_field_name: run_config}}}
            )
        if "query Models(" in body["query"]:
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
            return json.dumps(
                {
                    "data": {
                        "viewer": {
                            "entity": "mock_server_entity",
                            "flags": '{"code_saving_enabled": true}',
                            "teams": {
                                "edges": []  # TODO make configurable for cli_test
                            },
                        },
                        "serverInfo": {
                            "cliVersionInfo": {
                                "max_cli_version": str(
                                    ctx.get("max_cli_version", "0.10.33")
                                )
                            }
                        },
                    }
                }
            )
        if "query Sweep(" in body["query"]:
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
                {"data": {"createAgent": {"agent": {"id": "mock-server-agent-93xy",}}}}
            )
        if "mutation Heartbeat(" in body["query"]:
            return json.dumps(
                {
                    "data": {
                        "agentHeartbeat": {
                            "agent": {"id": "mock-server-agent-93xy",},
                            "commands": json.dumps(
                                [
                                    {
                                        "type": "run",
                                        "run_id": "mocker-sweep-run-x9",
                                        "args": {"learning_rate": {"value": 0.99124}},
                                    }
                                ]
                            ),
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
            if body["variables"].get("name") == "mocker-sweep-run-x9":
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
        if "mutation CreateArtifact(" in body["query"]:
            collection_name = body["variables"]["artifactCollectionNames"][0]
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
            return {"data": {"createArtifactManifest": {"artifactManifest": manifest,}}}
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
            return {"data": {"updateArtifactManifest": {"artifactManifest": manifest,}}}
        if "mutation CreateArtifactFiles" in body["query"]:
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
        if "query RunArtifacts(" in body["query"]:
            if "inputArtifacts" in body["query"]:
                key = "inputArtifacts"
            else:
                key = "outputArtifacts"
            artifacts = paginated(artifact(ctx), ctx)
            artifacts["totalCount"] = ctx["page_times"]
            return {"data": {"project": {"run": {key: artifacts}}}}
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
        if "query Artifact(" in body["query"]:
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
        if "query ClientIDMapping(" in body["query"]:
            return {"data": {"clientIDMapping": {"serverID": "QXJ0aWZhY3Q6NTI1MDk4"}}}
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

        print("MISSING QUERY, add me to tests/mock_server.py", body["query"])
        error = {"message": "Not implemented in tests/mock_server.py", "body": body}
        return json.dumps({"errors": [error]})

    @app.route("/storage", methods=["PUT", "GET"])
    def storage():
        ctx = get_ctx()
        if "fail_storage_times" in ctx:
            if ctx["fail_storage_count"] < ctx["fail_storage_times"]:
                ctx["fail_storage_count"] += 1
                return json.dumps({"errors": ["Server down"]}), 500
        file = request.args.get("file")
        _id = request.args.get("id", "")
        run = request.args.get("run", "unknown")
        ctx["storage"] = ctx.get("storage", {})
        ctx["storage"][run] = ctx["storage"].get(run, [])
        ctx["storage"][run].append(request.args.get("file"))
        size = ctx["files"].get(request.args.get("file"))
        if request.method == "GET" and size:
            return os.urandom(size), 200
        # make sure to read the data
        request.get_data()
        run_ctx = ctx["runs"].setdefault(run, default_ctx())
        for c in ctx, run_ctx:
            c["file_names"].append(request.args.get("file"))

        inject = InjectRequestsParse(ctx).find(request=request)
        if inject:
            if inject.response:
                response = inject.response
            if inject.http_status:
                # print("INJECT", inject, inject.http_status)
                raise HttpException("some error", status_code=inject.http_status)

        if request.method == "PUT":
            curr = ctx["file_bytes"].get(file)
            if curr is None:
                ctx["file_bytes"].setdefault(file, 0)
                ctx["file_bytes"][file] += request.content_length
            else:
                ctx["file_bytes"][file] += request.content_length
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
            elif _id == "6ddbe1c239de9c9fc6c397fc5591555a":
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
            return {
                "docker": "test/docker",
                "program": "train.py",
                "args": ["--test", "foo"],
                "git": ctx.get("git", {}),
            }
        elif file == "diff.patch":
            # TODO: make sure the patch is valid for windows as well,
            # and un skip the test in test_cli.py
            return r"""
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
        return "", 200

    @app.route("/artifacts/<entity>/<digest>", methods=["GET", "POST"])
    def artifact_file(entity, digest):
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

    @app.errorhandler(404)
    def page_not_found(e):
        print("Got request to: %s (%s)" % (request.url, request.method))
        return "Not Found", 404

    return app


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
                if k == u"output.log":
                    lines = [content]
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
    def dropped_chunks(self):
        return self._ctx.get("file_stream", [{"dropped": 0}])[-1]["dropped"]

    @property
    def summary_raw(self):
        fs_files = self.get_filestream_file_items()
        summary = fs_files.get("wandb-summary.json", [])[-1]
        return summary

    @property
    def summary_user(self):
        return {k: v for k, v in self.summary_raw.items() if not k.startswith("_")}

    @property
    def summary(self):
        # TODO: move this to config_user eventually
        return self.summary_raw

    @property
    def history(self):
        fs_files = self.get_filestream_file_items()
        history = fs_files.get("wandb-history.jsonl")
        return history

    @property
    def exit_code(self):
        exit_code = None
        fs_list = self._ctx.get("file_stream")
        if fs_list:
            exit_code = fs_list[-1].get("exitcode")
        return exit_code

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
        return self.config["_wandb"]["value"]

    @property
    def telemetry(self):
        return self.config.get("_wandb", {}).get("value", {}).get("t")

    @property
    def metrics(self):
        return self.config.get("_wandb", {}).get("value", {}).get("m")

    @property
    def manifests_created(self):
        return self._ctx.get("manifests_created") or []

    @property
    def manifests_created_ids(self):
        return [m["id"] for m in self.manifests_created]


if __name__ == "__main__":
    app = create_app()
    app.logger.setLevel(logging.INFO)
    app.run(debug=False, port=int(os.environ.get("PORT", 8547)))
