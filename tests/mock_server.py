"""Mock Server for simple calls the cli and public api makes"""

from flask import Flask, request
import os
from datetime import datetime
import json

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
            "edges": [{"node": {"name": "weights.h5", "sizeBytes": 20, "url": request.url_root + "/storage?file=weights.h5"}}]
        },
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
        if "fail_times" in ctx:
            if ctx["fail_count"] < ctx["fail_times"]:
                ctx["fail_count"] += 1
                return json.dumps({"errors": ["Server down"]}), 500
        body = request.get_json()
        if body["variables"].get("files"):
            file = body["variables"]["files"][0]
            return json.dumps({
                "data": {
                    "model": {
                        "bucket": {
                            "id": "storageid",
                            "files": {
                                "uploadHeaders": [],
                                "edges": [{"node": {"name": file, "url": request.url_root + "/storage?file=%s" % file}}]
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
                        "flags": '{"code_saving_enabled": true}'
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
                nodes.append({
                    "node" : {
                        "id": str(i),
                        "name": file_spec['name'],
                        "displayName": file_spec['name'],
                        "digest": "null",
                        "uploadUrl": request.url_root + "/storage?file=%s" % file_spec['name'],
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
            return {
                "data": {
                    "createArtifact": {
                        "artifact": artifact(ctx, body["variables"]["artifactCollectionNames"][0])
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
            key = "inputArtifacts" if "inputArtifacts" in body["query"] else "outputArtifacts"
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
            artifacts = paginated(artifact(ctx), ctx, {"version": "v%i" % ctx["page_count"]})
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
        print("MISSING QUERY", body["query"])
        return json.dumps({"errors": [{"message": "Not implemented in tests/mock_server.py", "body": body}]})

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
        if ctx.get("k8s"):
            return b'{"status":{"containerStatuses":[{"imageID":"docker-pullable://test@sha256:1234"}]}}', 200
        else:
            return b'', 500

    @app.errorhandler(404)
    def page_not_found(e):
        print("Got request to: %s (%s)" % (request.url, request.method))
        return "Not Found", 404

    return app


if __name__== '__main__':
    app = create_app()
