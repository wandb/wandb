import six
from wandb_graphql.language.parser import parse
from wandb_graphql.language.source import Source


def gql(request_string):
    if isinstance(request_string, six.string_types):
        source = Source(request_string, 'GraphQL request')
        return parse(source)
    else:
        raise Exception('Received incompatible request "{}".'.format(request_string))
