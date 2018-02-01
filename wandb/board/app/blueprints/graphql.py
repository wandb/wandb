from flask import Blueprint, current_app
import flask_cors
from flask_graphql import GraphQLView
from app.graphql.schema import schema


graphql = Blueprint('graphql', __name__)
flask_cors.CORS(graphql)

graphql.add_url_rule(
    '/graphql', view_func=GraphQLView.as_view('graphql', schema=schema, graphiql=True))
