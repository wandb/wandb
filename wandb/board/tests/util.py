import json
import pytest
import os
try:
    from urllib import urlencode
except ImportError:
    from urllib.parse import urlencode
from flask import url_for


def response_json(response):
    return json.loads(response.data.decode())


j = lambda **kwargs: json.dumps(kwargs)


def graphql_url(**url_params):
    string = url_for('graphql.graphql')

    if url_params:
        string += '?' + urlencode(url_params)

    return string


@pytest.fixture
def app(request):
    me = os.path.dirname(__file__)
    path = os.path.join(me, "fixtures/basic/wandb")
    marker = request.node.get_marker('base_path')
    if marker:
        path = os.path.join(
            me, "fixtures", marker.args[0], "wandb")
    from wandb.board.app import create_app
    return create_app("testing", path)
