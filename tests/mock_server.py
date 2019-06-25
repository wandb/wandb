from flask import Flask, request
import json
app = Flask(__name__)

@app.route("/graphql", methods=["POST"])
def graphql():
    body = request.get_json()
    if body["variables"].get("files"):
        file = body["variables"]["files"][0]
        return json.dumps({
            "data":{
                "model":{
                    "bucket":{
                        "id": "storageid",
                        "files":{
                            "edges":[{"node":{"name": file,"url": request.url_root + "/storage?file=%s" % file}}]
                        }
                    }
                }
            }
        })
    if "query Viewer" in body["query"]:
        return json.dumps({
            "data":{
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
                        "displayName": "lovely-dawn-32"
                    }
                }
            }
        })
    return json.dumps({"error": "Not implemented"})

@app.route("/storage", methods=["PUT"])
def storage():
    return "", 200

@app.route("/<entity>/<project>/<run>/file_stream", methods=["POST"])
def file_stream(entity, project, run):
    return json.dumps({"exitcode":None,"limits":{}})
