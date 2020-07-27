"""Mock Server for simple calls the cli and public api make"""

from flask import Flask, request
import os
import sys
from datetime import datetime
import json
import yaml
import wandb
from six.moves import urllib
from tests.utils.mock_requests import RequestsMock
# TODO: remove once python2 ripped out
if sys.version_info < (3, 5):
    from mock import patch
else:
    from unittest.mock import patch


def default_ctx():
    return {
        "fail_count": 0,
        "page_count": 0,
        "page_times": 2,
        "files": {},
        "k8s": False,
    }


def mock_server():
    ctx = default_ctx()
    app = create_app(ctx)
    mock = RequestsMock(app, ctx)
    # We mock out all requests libraries, couldn't find a way to mock the core lib
    patch("gql.transport.requests.requests", mock).start()
    patch("wandb.internal.file_stream.requests", mock).start()
    patch("wandb.internal.internal_api.requests", mock).start()
    patch("wandb.internal.update.requests", mock).start()
    patch("wandb.apis.internal_runqueue.requests", mock).start()
    patch("wandb.apis.public.requests", mock).start()
    patch("wandb.util.requests", mock).start()
    patch("wandb.wandb_sdk.wandb_artifacts.requests", mock).start()
    print("Patched requests everywhere", os.getpid())
    return mock


def run():
    return {
        'id': 'test',
        'name': 'wild-test',
        'displayName': 'beast-bug-33',
        'state': "running",
        'config': '{"epochs": {"value": 10}}',
        'description': "",
        'systemMetrics': '{"cpu": 100}',
        'summaryMetrics': '{"acc": 100, "loss": 0}',
        'fileCount': 1,
        'history': [
            '{"acc": 10, "loss": 90}',
            '{"acc": 20, "loss": 80}',
            '{"acc": 30, "loss": 70}'
        ],
        'events': [
            '{"cpu": 10}',
            '{"cpu": 20}',
            '{"cpu": 30}'
        ],
        "files": {
            # Special weights url meant to be used with api_mocks#download_url
            "edges": [{"node": {"name": "weights.h5", "sizeBytes": 20, 'md5': "XXX",
                                "url": request.url_root + "/storage?file=weights.h5"}}]
        },
        "sampledHistory": ['{"loss": 0, "acc": 100}'],
        "shouldStop": False,
        "failed": False,
        "stopped": False,
        "running": True,
        'tags': [],
        'notes': None,
        'sweepName': None,
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
        "labels": [],
        "metadata": "{}",
        "aliases": [{
            "artifactCollectionName": collection_name,
            "alias": "v%i" % ctx["page_count"]
        }]
    }


def paginated(node, ctx, extra={}):
    next_page = False
    ctx["page_count"] += 1
    if ctx["page_count"] < ctx["page_times"]:
        next_page = True
    edge = {
        "node": node,
        "cursor": "abc123"
    }
    edge.update(extra)
    return {
        "edges": [edge],
        "pageInfo": {
            "endCursor": "abc123",
            "hasNextPage": next_page
        }
    }


def create_app(ctx):
    app = Flask(__name__)

    @app.route("/graphql", methods=["POST"])
    def graphql():
        #  TODO: in tests wandb-username is set to the test name, lets scope ctx to it
        test_name = request.headers.get("X-WANDB-USERNAME")
        app.logger.info("Test request from: %s", test_name)
        if "fail_times" in ctx:
            if ctx["fail_count"] < ctx["fail_times"]:
                ctx["fail_count"] += 1
                return json.dumps({"errors": ["Server down"]}), 500
        body = request.get_json()
        if body["variables"].get("files"):
            file = body["variables"]["files"][0]
            url = request.url_root + "/storage?file=%s" % urllib.parse.quote(file)
            return json.dumps({
                "data": {
                    "model": {
                        "bucket": {
                            "id": "storageid",
                            "files": {
                                "uploadHeaders": [],
                                "edges": [{"node": {"name": file, "url": url}}]
                            }
                        }
                    }
                }
            })
        if "historyTail" in body["query"]:
            return json.dumps({
                'data': {
                    'model': {
                        'bucket': {
                            'name': "test",
                            'displayName': 'funky-town-13',
                            'id': "test",
                            'summaryMetrics': '{"acc": 10}',
                            'logLineCount': 14,
                            'historyLineCount': 15,
                            'eventsLineCount': 0,
                            'historyTail': '["{\\"_step\\": 15, \\"acc\\": 1}"]',
                            'eventsTail': '[]'
                        }
                    }
                }
            })
        if "query Runs(" in body["query"]:
            return json.dumps({
                "data": {
                    "project": {
                        "runCount": 4,
                        "readOnly": False,
                        "runs": paginated(run(), ctx)
                    }
                }
            })
        if "query Run(" in body["query"]:
            return json.dumps({
                'data': {
                    'project': {
                        'run': run()
                    }
                }
            })
        if "query Model(" in body["query"]:
            return json.dumps({
                'data': {
                    'model': {
                        'bucket': run()
                    }
                }
            })
        if "query Models(" in body["query"]:
            return json.dumps({
                'data': {
                    'models': {
                        "edges": [{"node": {"id": "123", "name": "myname", "project": "myproj"}}]
                    }
                }
            })
        if "query Projects(" in body["query"]:
            return json.dumps({
                "data": {
                    "models": paginated({
                        "id": "1",
                        "name": "test-project",
                        "entityName": body["variables"]["entity"],
                        "createdAt": "now",
                        "isBenchmark": False,
                    }, ctx)
                }
            })
        if "query Viewer " in body["query"]:
            return json.dumps({
                "data": {
                    "viewer": {
                        "entity": "vanpelt",
                        "flags": '{"code_saving_enabled": true}',
                        "teams": {
                            "edges": []  # TODO make configurable for cli_test
                        }
                    }
                }
            })
        if "query Sweep(" in body["query"]:
            return json.dumps({
                "data": {
                    "project": {
                        "sweep": {
                            "id": "1234",
                            "name": "fun-sweep-10",
                            "state": "running",
                            "bestLoss": 0.33,
                            "config": yaml.dump({"metric": {"name": "loss",
                                                            "value": "minimize"}}),
                            "createdAt": datetime.now().isoformat(),
                            "heartbeatAt": datetime.now().isoformat(),
                            "updatedAt": datetime.now().isoformat(),
                            "earlyStopJobRunning": False,
                            "controller": None,
                            "scheduler": None,
                            "runs": paginated(run(), ctx)
                        }
                    }
                }
            })
        if "mutation UpsertSweep(" in body["query"]:
            return json.dumps({
                "data": {
                    "upsertSweep": {
                        "sweep": {
                            "name": "test",
                            "project": {
                                "id": "1234",
                                "name": "test",
                                "entity": {
                                    "id": "1234",
                                    "name": "test"
                                }
                            }
                        }
                    }
                }
            })
        if "mutation UpsertBucket(" in body["query"]:
            return json.dumps({
                "data": {
                    "upsertBucket": {
                        "bucket": {
                            "id": "storageid",
                            "name": body["variables"].get("name", "abc123"),
                            "displayName": "lovely-dawn-32",
                            "project": {
                                "name": "test",
                                "entity": {
                                    "name": "mock_server_entity"
                                }
                            }
                        }
                    }
                }
            })
        if "mutation CreateAnonymousApiKey " in body["query"]:
            return json.dumps({
                "data": {
                    "createAnonymousEntity": {
                        "apiKey": {
                            "name": "ANONYMOOSE" * 4
                        }
                    }
                }
            })
        if "mutation PrepareFiles(" in body["query"]:
            nodes = []
            for i, file_spec in enumerate(body['variables']['fileSpecs']):
                url = request.url_root + "/storage?file=%s" % file_spec['name']
                nodes.append({
                    "node": {
                        "id": str(i),
                        "name": file_spec['name'],
                        "displayName": file_spec['name'],
                        "digest": "null",
                        "uploadUrl": url,
                        "uploadHeaders": ""
                    }})
            return json.dumps({
                "data": {
                    "prepareFiles": {
                        "files": {
                            "edges": nodes
                        }
                    }
                }
            })
        if "mutation CreateArtifact(" in body["query"]:
            collection_name = body["variables"]["artifactCollectionNames"][0]
            return {
                "data": {
                    "createArtifact": {
                        "artifact": artifact(ctx, collection_name)
                    }
                }
            }
        if "mutation UseArtifact(" in body["query"]:
            return {
                "data": {
                    "useArtifact": {
                        "artifact": artifact(ctx)
                    }
                }
            }
        if "query ProjectArtifactType(" in body["query"]:
            return {
                "data": {
                    "project": {
                        "artifactType": {
                            "id": "1",
                            "name": "dataset",
                            "description": "",
                            "createdAt": datetime.now().isoformat()
                        }
                    }
                }
            }
        if "query ProjectArtifacts(" in body["query"]:
            return {
                "data": {
                    "project": {
                        "artifactTypes": paginated({
                            "id": "1",
                            "name": "dataset",
                            "description": "",
                            "createdAt": datetime.now().isoformat()
                        }, ctx)
                    }
                }
            }
        if "query ProjectArtifactCollections(" in body["query"]:
            return {
                "data": {
                    "project": {
                        "artifactType": {
                            "artifactSequences": paginated({
                                "id": "1",
                                "name": "mnist",
                                "description": "",
                                "createdAt": datetime.now().isoformat()
                            }, ctx)
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
            return {
                "data": {
                    "project": {
                        "run": {
                            key: artifacts
                        }
                    }
                }
            }
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
                                "artifacts": artifacts
                            }
                        }
                    }
                }
            }
        if "query Artifact(" in body["query"]:
            art = artifact(ctx)
            art["artifactType"] = {
                "id": 1,
                "name": "dataset"
            }
            art["currentManifest"] = {
                "id": 1,
                "file": {
                    "id": 1,
                    "url": request.url_root + "/storage?file=wandb_manifest.json"
                }
            }
            return {
                "data": {
                    "project": {
                        "artifact": art
                    }
                }
            }
        if "stopped" in body["query"]:
            return json.dumps({
                "data": {
                    "Model": {
                        "project": {
                            "run": {
                                "stopped": False
                            }
                        }
                    }
                }
            })
        print("MISSING QUERY, add me to tests/mock_server.py", body["query"])
        error = {"message": "Not implemented in tests/mock_server.py", "body": body}
        return json.dumps({"errors": [error]})

    @app.route("/storage", methods=["PUT", "GET"])
    def storage():
        file = request.args.get('file')
        size = ctx["files"].get(request.args.get('file'))
        if request.method == "GET" and size:
            return os.urandom(size), 200
        if file == "wandb_manifest.json":
            return {
                "version": 1,
                "storagePolicy": "wandb-storage-policy-v1",
                "storagePolicyConfig": {},
                "contents": {
                    "digits.h5": {
                        "digest": "TeSJ4xxXg0ohuL5xEdq2Ew==",
                        "size": 81299
                    }
                }}
        return "", 200

    @app.route("/artifacts/<entity>/<digest>", methods=["GET", "POST"])
    def artifact_file(entity, digest):
        return "ARTIFACT %s" % digest, 200

    @app.route("/files/<entity>/<project>/<run>/file_stream", methods=["POST"])
    def file_stream(entity, project, run):
        return json.dumps({"exitcode": None, "limits": {}})

    @app.route("/api/v1/namespaces/default/pods/test")
    def k8s_pod():
        image_id = b"docker-pullable://test@sha256:1234"
        ms = b'{"status":{"containerStatuses":[{"imageID":"%s"}]}}' % image_id
        if ctx.get("k8s"):
            return ms, 200
        else:
            return b'', 500

    @app.route("/pypi/<library>/json")
    def pypi(library):
        return json.dumps({
            "info": {
                "version": wandb.__version__},
            "releases": {
                "88.1.2rc2": [],
                "88.1.2rc12": [],
                "88.1.2rc3": [],
                "88.1.2rc4": [],
                "0.0.8rc6": [],
                "0.0.8rc2": [],
                "0.0.8rc3": [],
                "0.0.8rc8": [],
                "0.0.7": [],
                "0.0.5": [],
                "0.0.6": [],
            }})

    @app.errorhandler(404)
    def page_not_found(e):
        print("Got request to: %s (%s)" % (request.url, request.method))
        return "Not Found", 404

    return app


if __name__ == '__main__':
    app = create_app(default_ctx())
    app.run(debug=True, port=int(os.environ.get("PORT", 8547)))
