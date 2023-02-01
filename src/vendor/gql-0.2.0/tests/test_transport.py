import pytest
import requests
import vcr

from gql import Client, gql
from gql.transport.requests import RequestsHTTPTransport

# https://github.com/graphql-python/swapi-graphene
URL = 'http://127.0.0.1:8000/graphql'


@pytest.fixture
def client():
    with vcr.use_cassette('tests/fixtures/vcr_cassettes/client.yaml'):
        request = requests.get(
            URL,
            headers={
                'Host': 'swapi.graphene-python.org',
                'Accept': 'text/html',
            }
        )
        request.raise_for_status()
        csrf = request.cookies['csrftoken']

        return Client(
            transport=RequestsHTTPTransport(
                url=URL,
                cookies={"csrftoken": csrf},
                headers={'x-csrftoken':  csrf}),
            fetch_schema_from_transport=True
        )


def test_hero_name_query(client):
    query = gql('''
    {
      myFavoriteFilm: film(id:"RmlsbToz") {
        id
        title
        episodeId
        characters(first:5) {
          edges {
            node {
              name
            }
          }
        }
      }
    }
    ''')
    expected = {
        "myFavoriteFilm": {
            "id": "RmlsbToz",
            "title": "Return of the Jedi",
            "episodeId": 6,
            "characters": {
                "edges": [
                  {
                      "node": {
                          "name": "Luke Skywalker"
                      }
                  },
                    {
                      "node": {
                          "name": "C-3PO"
                      }
                  },
                    {
                      "node": {
                          "name": "R2-D2"
                      }
                  },
                    {
                      "node": {
                          "name": "Darth Vader"
                      }
                  },
                    {
                      "node": {
                          "name": "Leia Organa"
                      }
                  }
                ]
            }
        }
    }
    with vcr.use_cassette('tests/fixtures/vcr_cassettes/execute.yaml'):
        result = client.execute(query)
        assert result == expected
