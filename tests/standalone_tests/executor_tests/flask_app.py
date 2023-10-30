import argparse

import wandb
from flask import Flask, jsonify

app = Flask(__name__)


@app.route("/wandb", methods=["GET"])
def test_uwsgi():
    with wandb.init() as run:
        dataset_name = "check_uwsgi_flask"
        artifact = wandb.Artifact(dataset_name, type="dataset")
        artifact.metadata["datasetName"] = dataset_name
        run.log_artifact(artifact)
    return jsonify(status="success", run=run.name), 200


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a Flask app.")
    parser.add_argument(
        "--port", "-p", type=int, default=5000, help="The port to run the app on."
    )
    args = parser.parse_args()

    app.run(port=args.port)
