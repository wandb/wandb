from flask import Blueprint, current_app, send_from_directory, abort
from wandb.board.app.graphql.loader import find_run
import os

files = Blueprint('files', __name__)


@files.route("/board/default/runs/<run_id>/<filename>", methods=['GET'])
def serve_run_file(run_id, filename):
    run = find_run(run_id)
    if run:
        return send_from_directory(os.path.join(os.path.abspath(run.path), "media", "images"), filename)
    else:
        abort(404)


@files.route("/<path:path>")
def serve_file(path):
    return send_from_directory(current_app.template_folder, path)
