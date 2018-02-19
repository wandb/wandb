from flask import Blueprint
import flask_cors
import logging
import traceback
from flask_graphql import GraphQLView
from wandb.board.app.graphql.schema import schema
from wandb.board.app.util.errors import format_error

logger = logging.getLogger(__name__)

graphql = Blueprint('graphql', __name__)
flask_cors.CORS(graphql)
GraphQLView.format_error = format_error


graphql.add_url_rule(
    '/graphql', view_func=GraphQLView.as_view('graphql', schema=schema, graphiql=True))
