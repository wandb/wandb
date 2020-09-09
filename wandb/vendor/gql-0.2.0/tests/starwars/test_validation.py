import pytest
from graphql import graphql
from graphql.utils.introspection_query import introspection_query

from gql import Client, gql

from .schema import StarWarsSchema

introspection = graphql(StarWarsSchema, introspection_query).data


@pytest.fixture
def local_schema():
    return Client(schema=StarWarsSchema)


@pytest.fixture
def typedef_schema():
    return Client(type_def='''
schema {
  query: Query
}

interface Character {
  appearsIn: [Episode]
  friends: [Character]
  id: String!
  name: String
}

type Droid implements Character {
  appearsIn: [Episode]
  friends: [Character]
  id: String!
  name: String
  primaryFunction: String
}

enum Episode {
  EMPIRE
  JEDI
  NEWHOPE
}

type Human implements Character {
  appearsIn: [Episode]
  friends: [Character]
  homePlanet: String
  id: String!
  name: String
}

type Query {
  droid(id: String!): Droid
  hero(episode: Episode): Character
  human(id: String!): Human
}''')


@pytest.fixture
def introspection_schema():
    return Client(introspection=introspection)


@pytest.fixture(params=['local_schema', 'typedef_schema', 'introspection_schema'])
def client(request):
    return request.getfixturevalue(request.param)


def validation_errors(client, query):
    query = gql(query)
    try:
        client.validate(query)
        return False
    except Exception:
        return True


def test_nested_query_with_fragment(client):
    query = '''
        query NestedQueryWithFragment {
          hero {
            ...NameAndAppearances
            friends {
              ...NameAndAppearances
              friends {
                ...NameAndAppearances
              }
            }
          }
        }
        fragment NameAndAppearances on Character {
          name
          appearsIn
        }
    '''
    assert not validation_errors(client, query)


def test_non_existent_fields(client):
    query = '''
        query HeroSpaceshipQuery {
          hero {
            favoriteSpaceship
          }
        }
    '''
    assert validation_errors(client, query)


def test_require_fields_on_object(client):
    query = '''
        query HeroNoFieldsQuery {
          hero
        }
    '''
    assert validation_errors(client, query)


def test_disallows_fields_on_scalars(client):
    query = '''
        query HeroFieldsOnScalarQuery {
          hero {
            name {
              firstCharacterOfName
            }
          }
        }
    '''
    assert validation_errors(client, query)


def test_disallows_object_fields_on_interfaces(client):
    query = '''
        query DroidFieldOnCharacter {
          hero {
            name
            primaryFunction
          }
        }
    '''
    assert validation_errors(client, query)


def test_allows_object_fields_in_fragments(client):
    query = '''
        query DroidFieldInFragment {
          hero {
            name
            ...DroidFields
          }
        }
        fragment DroidFields on Droid {
          primaryFunction
        }
    '''
    assert not validation_errors(client, query)


def test_allows_object_fields_in_inline_fragments(client):
    query = '''
        query DroidFieldInFragment {
          hero {
            name
            ... on Droid {
              primaryFunction
            }
          }
        }
    '''
    assert not validation_errors(client, query)
