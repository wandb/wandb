import pytest
import mock

from gql import Client, gql
from gql.transport.requests import RequestsHTTPTransport


@mock.patch('gql.transport.requests.RequestsHTTPTransport.execute')
def test_retries(execute_mock):
    expected_retries = 3
    execute_mock.side_effect = Exception("fail")

    client = Client(
        retries=expected_retries,
        transport=RequestsHTTPTransport(url='http://swapi.graphene-python.org/graphql')
    )

    query = gql('''
    {
      myFavoriteFilm: film(id:"RmlsbToz") {
        id
        title
        episodeId
      }
    }
    ''')

    with pytest.raises(Exception):
        client.execute(query)

    assert execute_mock.call_count == expected_retries
