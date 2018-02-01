from flask import Blueprint, current_app, render_template, send_from_directory
import flask_cors
from flask_graphql import GraphQLView
from wandb.board.app.graphql.schema import schema


graphql = Blueprint('graphql', __name__)
flask_cors.CORS(graphql)


@graphql.route("/")
def index():
    return render_template("index.html")


graphql.add_url_rule(
    '/graphql', view_func=GraphQLView.as_view('graphql', schema=schema, graphiql=True))


@graphql.route("/<path:path>")
def serve_file(path):
    return send_from_directory(current_app.template_folder, path)


@graphql.errorhandler(404)
def lost_index(e):
    return render_template("index.html")
