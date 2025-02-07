import wandb
from wandb.apis.public._gql_compat import rewrite_gql_request
from wandb_gql import gql
from wandb_graphql import build_client_schema, introspection_query, print_ast


def test_gql_compat(api: wandb.Api):
    schema = build_client_schema(api.client.execute(gql(introspection_query)))

    original_query_str = """
        fragment UnsupportedFragment on UnsupportedType {
            __typename
            unsupportedFragmentField1
        }

        mutation CreateGenericWebhookIntegration($params: CreateGenericWebhookIntegrationInput!) {
            createGenericWebhookIntegration(input: $params) {
                integration {
                    __typename
                    ...GenericWebhookIntegrationFields
                    ... on SlackIntegration {
                        unsupportedField
                    }
                }
            }
        }

        fragment GenericWebhookIntegrationFields on GenericWebhookIntegration {
            __typename
            id
            unsupportedFragmentField2
            name
        }
        """
    expected_query_str = """
        mutation CreateGenericWebhookIntegration($params: CreateGenericWebhookIntegrationInput!) {
          createGenericWebhookIntegration(input: $params) {
            integration {
              __typename
              ...GenericWebhookIntegrationFields
            }
          }
        }
        fragment GenericWebhookIntegrationFields on GenericWebhookIntegration {
          __typename
          id
          name
        }
        """

    original_query = gql(original_query_str)
    expected_query = gql(expected_query_str)

    rewritten_query = rewrite_gql_request(schema, original_query)
    assert print_ast(rewritten_query) == print_ast(expected_query)
