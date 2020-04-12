"""Mock Server for simple tasks the cli does"""

from flask import Flask, request
import json


def create_app():
    app = Flask(__name__)

    @app.route("/graphql", methods=["POST"])
    def graphql():
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
        if "query Run" in body["query"]:
            return json.dumps({
                'data': {
                    'project': {
                        'run': {
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
                                "edges": [{"node": {"name": "weights.h5", "sizeBytes": 20, "url": "https://weights.url"}}]
                            },
                            'tags': [],
                            'notes': None,
                            'sweepName': None,
                        }
                    }
                }
            })
        if "query Viewer" in body["query"]:
            return json.dumps({
                "data": {
                    "viewer": {
                        "entity": "vanpelt"
                    }
                }
            })
        if "mutation UpsertBucket" in body["query"]:
            return json.dumps({
                "data": {
                    "upsertBucket": {
                        "bucket": {
                            "id": "storageid",
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
        return json.dumps({"error": "Not implemented in tests/mock_server.py", "body": body})

    @app.route("/storage", methods=["PUT", "GET"])
    def storage():
        return "", 200

    @app.route("/files/<entity>/<project>/<run>/file_stream", methods=["POST"])
    def file_stream(entity, project, run):
        return json.dumps({"exitcode": None, "limits": {}})

    @app.errorhandler(404)
    def page_not_found(e):
        print("Got request to: %s" % e)
        return "Not Found", 404

    return app


if __name__== '__main__':
    app = create_app()
