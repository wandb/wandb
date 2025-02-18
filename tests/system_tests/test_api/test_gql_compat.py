from pytest import fixture
from wandb.apis.public._gql_compat import SchemaInfo, gql_compat
from wandb.apis.public.api import RetryingClient
from wandb_gql import gql
from wandb_graphql import print_ast


@fixture
def client(user, api) -> RetryingClient:
    return api.client


@fixture
def schema_info(client) -> SchemaInfo:
    return client.schema_info


def test_gql_compat(schema_info):
    orig_query_str = """
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

    rewritten_query = gql_compat(orig_query_str, schema_info)
    assert print_ast(rewritten_query) == print_ast(expected_query)


def test_gql_compat_with_unsupported_fragment_spreads(schema_info):
    orig_query_str = """
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

    rewritten_query = gql_compat(orig_query_str, schema_info)
    assert print_ast(rewritten_query) == print_ast(expected_query)


def test_gql_compat_with_unsupported_fields(schema_info):
    orig_query_str = """
        query {
            viewer {
                id
                unsupportedField
            }
        }
        """

    expected_query = gql(
        """
        query {
            viewer {
                id
            }
        }
        """
    )

    rewritten_query = gql_compat(orig_query_str, schema_info)
    assert print_ast(rewritten_query) == print_ast(expected_query)


def test_gql_compat_with_empty_selection_set_after_rewriting(schema_info):
    orig_query_str = """
        query {
            viewer {
                id
                userEntity {
                    unsupportedField
                }
            }
        }
        """

    expected_query = gql(
        """
        query {
            viewer {
                id
            }
        }
        """
    )

    rewritten_query = gql_compat(orig_query_str, schema_info)
    assert print_ast(rewritten_query) == print_ast(expected_query)
