from .util import graphql_url, j, response_json, app
from wandb.board.app.graphql.loader import settings, data
from wandb.board.app.models.files import Description
from mock import MagicMock, patch


def test_project(client):
    response = client.get(graphql_url(
        query='{ model { description }}'))
    print(response_json(response))
    assert response.status_code == 200


def test_runs(client):
    response = client.get(graphql_url(
        query='{ model { buckets { edges { node { name }} }}}'))
    body = response_json(response)
    print(body)
    assert response.status_code == 200
    assert len(body["data"]["model"]["buckets"]["edges"]) == 3


def test_logs(client):
    response = client.get(graphql_url(
        query='{ model { bucket(name: "rmwhmprr") { logLines { edges { node { id line level}}}}}}'))
    body = response_json(response)
    assert response.status_code == 200
    assert len(body["data"]["model"]["bucket"]["logLines"]["edges"]) == 1078


def test_history(client):
    response = client.get(graphql_url(
        query='{ model { bucket(name: "rmwhmprr") { history }}}'))
    body = response_json(response)
    assert response.status_code == 200
    assert len(body["data"]["model"]["bucket"]["history"]) == 12


def test_state(client):
    response = client.get(graphql_url(
        query='{ model { buckets { edges { node { state }} }}}'))
    body = response_json(response)
    print(body)
    assert response.status_code == 200
    assert [e["node"]["state"]
            for e in body["data"]["model"]["buckets"]["edges"]] == ["killed", "failed", "crashed"]


def test_upsert_project(client):
    settings.save = MagicMock()
    response = client.post(graphql_url(), content_type='application/json', data=j(query='''
        mutation Test { upsertModel(input: { id: "default", description: "My desc" }) { model { description } inserted } } 
        '''))
    assert response.status_code == 200
    assert not response_json(response)['data']['upsertModel']['inserted']
    assert settings.save.called


@patch.object(Description, 'mutate')
def test_upsert_run(mock, client):
    print(data['Runs'][0].description)
    response = client.post(graphql_url(), content_type='application/json', data=j(query='''
        mutation Test { upsertBucket(input: { id: "rmwhmprr", description: "My desc" }) { bucket { description } inserted } } 
        '''))
    assert not response_json(response)['data']['upsertBucket']['inserted']
    assert response.status_code == 200
    assert mock.called
