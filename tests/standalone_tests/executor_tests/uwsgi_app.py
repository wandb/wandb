from flask import Flask, jsonify
import wandb

app = Flask(__name__)


@app.route("/wandb", methods=["GET"])
def test_uwsgi():
    with wandb.init(settings={"console": "off"}) as run:
        dataset_name = "check_uwsgi_flask"
        artifact = wandb.Artifact(dataset_name, type="dataset")
        artifact.metadata["datasetName"] = dataset_name
        run.log_artifact(artifact)
    return jsonify(status="success", run=run.name), 200
