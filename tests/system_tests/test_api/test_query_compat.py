from pytest import fixture
from wandb.apis.public._query_compat import gql_compat
from wandb_gql import gql
from wandb_graphql import print_ast


@fixture
def client(user, api):
    return api.client


@fixture
def schema_info(client):
    return client.schema_info


def test_gql_compat(schema_info):
    orig_query = gql(
        """
        fragment unsupportedFragment1 on unsupportedType {
            unsupportedFragmentField1
        }
        query {
            viewer {
                id
                unsupportedField
                ... unsupportedFragment1
                ... unsupportedFragment2
                userEntity {
                    __typename
                    id
                    nestedUnsupportedField
                }
                defaultEntity {
                    onlyNestedUnsupportedField
                }
                ... undefinedFragment
            }
        }
        fragment unsupportedFragment2 on unsupportedType {
            unsupportedFragmentField2
        }
        """
    )

    expected_query = gql(
        """
        query {
            viewer {
                id
                userEntity {
                    __typename
                    id
                }
            }
        }
        """
    )

    rewritten_query = gql_compat(orig_query, schema_info)
    assert print_ast(rewritten_query) == print_ast(expected_query)


def test_gql_compat_with_unsupported_fragment_spreads(schema_info):
    query = gql(
        """
        fragment unsupportedFragment1 on unsupportedType {
            unsupportedFragmentField1
        }
        query {
            viewer {
                id
                ... unsupportedFragment1
                ... unsupportedFragment2
                userEntity {
                    id
                }
                ... undefinedFragment
            }
        }
        fragment unsupportedFragment2 on unsupportedType {
            unsupportedFragmentField2
        }
        """
    )

    expected_query = gql(
        """
        query {
            viewer {
                id
                userEntity {
                    id
                }
            }
        }
        """
    )

    rewritten_query = gql_compat(query, schema_info)
    assert print_ast(rewritten_query) == print_ast(expected_query)
