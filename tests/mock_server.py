"""Mock Server for simple calls the cli and public api makes"""

from flask import Flask, request
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

def paginated(node, ctx):
    next_page = False
    print("Paginating ", ctx["page_count"], ctx["page_times"])
    ctx["page_count"] += 1
    if ctx["page_count"] < ctx["page_times"]:
        next_page = True
    return {
        "edges": [{
            "node": node,
            "cursor": "abc123"
        }],
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
        if "query Runs" in body["query"]:
            return json.dumps({
                "data": {
                    "project": {
                        "runCount": 4,
                        "readOnly": False,
                        "runs": paginated(run(), ctx)
                    }
                }
            })
        if "query Run" in body["query"]:
            return json.dumps({
                'data': {
                    'project': {
                        'run': run()
                    }
                }
            })
        if "query Projects" in body["query"]:
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
        if "query Viewer" in body["query"]:
            return json.dumps({
                "data": {
                    "viewer": {
                        "entity": "vanpelt",
                        "flags": '{"code_saving_enabled": true}'
                    }
                }
            })
        if "mutation UpsertBucket" in body["query"]:
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
        if "mutation CreateAnonymousApiKey" in body["query"]:
            return json.dumps({
                "data": {
                    "createAnonymousEntity": {
                        "apiKey": {
                            "name": "ANONYMOOSE" * 4
                        }
                    }
                }
            })
        if "mutation PrepareFiles" in body["query"]:
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
        return json.dumps({"errors": [{"message": "Not implemented in tests/mock_server.py", "body": body}]})

    @app.route("/storage", methods=["PUT", "GET"])
    def storage():
        return "", 200

    @app.route("/files/<entity>/<project>/<run>/file_stream", methods=["POST"])
    def file_stream(entity, project, run):
        return json.dumps({"exitcode": None, "limits": {}})

    @app.errorhandler(404)
    def page_not_found(e):
        print("Got request to: %s" % request.url)
        return "Not Found", 404

    return app


if __name__== '__main__':
    app = create_app()
