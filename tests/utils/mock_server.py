"""Mock Server for simple calls the cli and public api make"""

from flask import Flask, request, g
import os
import sys
from datetime import datetime, timedelta
import json
import yaml

# HACK: restore first two entries of sys path after wandb load
save_path = sys.path[:2]
import wandb

sys.path[0:0] = save_path
import logging
from six.moves import urllib
import threading
from tests.utils.mock_requests import RequestsMock


def default_ctx():
    return {
        "fail_graphql_count": 0,  # used via "fail_graphql_times"
        "fail_storage_count": 0,  # used via "fail_storage_times"
        "page_count": 0,
        "page_times": 2,
        "requested_file": "weights.h5",
        "current_run": None,
        "files": {},
        "k8s": False,
        "resume": False,
    }


def mock_server(mocker):
    ctx = default_ctx()
    app = create_app(ctx)
    mock = RequestsMock(app, ctx)
    # We mock out all requests libraries, couldn't find a way to mock the core lib
    sdk_path = "wandb.sdk"
    mocker.patch("gql.transport.requests.requests", mock)
    mocker.patch("wandb.wandb_sdk.internal.file_stream.requests", mock)
    mocker.patch("wandb.wandb_sdk.internal.internal_api.requests", mock)
    mocker.patch("wandb.wandb_sdk.internal.update.requests", mock)
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

    # for wandb_tests::wandb_restore_name_not_found
    # if there is a fileName query, and this query is for nofile.h5
    # return an empty file. otherwise, return the usual weights.h5
    if ctx.get("graphql"):
        fileNames = ctx["graphql"][-1]["variables"].get("fileNames")
    else:
        fileNames = None
    if fileNames == ["nofile.h5"]:
        fileNode = {
            "name": "nofile.h5",
            "sizeBytes": 0,
            "md5": "0",
            "url": request.url_root + "/storage?file=nofile.h5",
        }
    else:
        fileNode = {
            "name": ctx["requested_file"],
            "sizeBytes": 20,
            "md5": "XXX",
            "url": request.url_root + "/storage?file=%s" % ctx["requested_file"],
            "directUrl": request.url_root
            + "/storage?file=%s&direct=true" % ctx["requested_file"],
        }

    return {
        "id": "test",
        "name": "test",
        "displayName": "beast-bug-33",
        "state": "running",
        "config": '{"epochs": {"value": 10}}',
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


def artifact(ctx, collection_name="mnist"):
    return {
        "id": ctx["page_count"],
        "digest": "abc123",
        "description": "",
        "state": "COMMITTED",
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


def set_ctx(ctx):
    get_ctx()
    g.ctx.set(ctx)


def _bucket_config():
    return {
        "commit": "HEAD",
        "github": "https://github.com/vanpelt",
        "config": '{"foo":{"value":"bar"}}',
        "files": {
            "edges": [
                {
                    "node": {
                        "directUrl": request.url_root
                        + "/storage?file=wandb-metadata.json",
                        "name": "wandb-metadata.json",
                    }
                },
                {
                    "node": {
                        "directUrl": request.url_root + "/storage?file=diff.patch",
                        "name": "diff.patch",
                    }
                },
            ]
        },
    }


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
        test_name = request.headers.get("X-WANDB-USERNAME")
        app.logger.info("Test request from: %s", test_name)
        if "fail_graphql_times" in ctx:
            if ctx["fail_graphql_count"] < ctx["fail_graphql_times"]:
                ctx["fail_graphql_count"] += 1
                return json.dumps({"errors": ["Server down"]}), 500
        body = request.get_json()
        if body["variables"].get("run"):
            ctx["current_run"] = body["variables"]["run"]
        if body["variables"].get("files"):
            ctx["requested_file"] = body["variables"]["files"][0]
            url = request.url_root + "/storage?file={}&run={}".format(
                urllib.parse.quote(ctx["requested_file"]), ctx["current_run"]
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
                                                "name": ctx["requested_file"],
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
                run_config = _bucket_config()
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
                        }
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
                                    {"metric": {"name": "loss", "value": "minimize"}}
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
                            }
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
                                        "run_id": "mocker-server-run-x9",
                                        "args": {"learning_rate": {"value": 0.99124}},
                                    }
                                ]
                            ),
                        }
                    }
                }
            )
        if "mutation UpsertBucket(" in body["query"]:
            return json.dumps(
                {
                    "data": {
                        "upsertBucket": {
                            "bucket": {
                                "id": "storageid",
                                "name": body["variables"].get("name", "abc123"),
                                "displayName": "lovely-dawn-32",
                                "project": {
                                    "name": "test",
                                    "entity": {"name": "mock_server_entity"},
                                },
                            },
                            "inserted": ctx["resume"] is False,
                        }
                    }
                }
            )
        if "mutation CreateAnonymousApiKey " in body["query"]:
            return json.dumps(
                {
                    "data": {
                        "createAnonymousEntity": {"apiKey": {"name": "ANONYMOOSE" * 4}}
                    }
                }
            )
        if "mutation PrepareFiles(" in body["query"]:
            nodes = []
            for i, file_spec in enumerate(body["variables"]["fileSpecs"]):
                url = request.url_root + "/storage?file=%s" % file_spec["name"]
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
            return {
                "data": {"createArtifact": {"artifact": artifact(ctx, collection_name)}}
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
            art = artifact(ctx)
            art["artifactType"] = {"id": 1, "name": "dataset"}
            return {"data": {"project": {"artifact": art}}}
        if "query ArtifactManifest(" in body["query"]:
            art = artifact(ctx)
            art["currentManifest"] = {
                "id": 1,
                "file": {
                    "id": 1,
                    "directUrl": request.url_root + "/storage?file=wandb_manifest.json",
                },
            }
            return {"data": {"project": {"artifact": art}}}
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
        run = request.args.get("run", "unknown")
        ctx["storage"] = ctx.get("storage", {})
        ctx["storage"][run] = ctx["storage"].get(run, [])
        ctx["storage"][run].append(request.args.get("file"))
        size = ctx["files"].get(request.args.get("file"))
        if request.method == "GET" and size:
            return os.urandom(size), 200
        # make sure to read the data
        request.get_data()
        if file == "wandb_manifest.json":
            return {
                "version": 1,
                "storagePolicy": "wandb-storage-policy-v1",
                "storagePolicyConfig": {},
                "contents": {
                    "digits.h5": {"digest": "TeSJ4xxXg0ohuL5xEdq2Ew==", "size": 81299},
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
        return "ARTIFACT %s" % digest, 200

    @app.route("/files/<entity>/<project>/<run>/file_stream", methods=["POST"])
    def file_stream(entity, project, run):
        ctx = get_ctx()
        ctx["file_stream"] = ctx.get("file_stream", [])
        ctx["file_stream"].append(request.get_json())
        return json.dumps({"exitcode": None, "limits": {}})

    @app.route("/api/v1/namespaces/default/pods/test")
    def k8s_pod():
        ctx = get_ctx()
        image_id = b"docker-pullable://test@sha256:1234"
        ms = b'{"status":{"containerStatuses":[{"imageID":"%s"}]}}' % image_id
        if ctx.get("k8s"):
            return ms, 200
        else:
            return b"", 500

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


if __name__ == "__main__":
    app = create_app()
    app.logger.setLevel(logging.INFO)
    app.run(debug=False, port=int(os.environ.get("PORT", 8547)))
