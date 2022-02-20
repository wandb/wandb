from six.moves.collections_abc import Iterable

from .definition import GraphQLObjectType
from .directives import GraphQLDirective, specified_directives
from .introspection import IntrospectionSchema
from .typemap import GraphQLTypeMap


class GraphQLSchema(object):
    """Schema Definition

    A Schema is created by supplying the root types of each type of operation, query and mutation (optional).
    A schema definition is then supplied to the validator and executor.

    Example:

        MyAppSchema = GraphQLSchema(
            query=MyAppQueryRootType,
            mutation=MyAppMutationRootType,
        )

    Note: If an array of `directives` are provided to GraphQLSchema, that will be
    the exact list of directives represented and allowed. If `directives` is not
    provided then a default set of the specified directives (e.g. @include and
    @skip) will be used. If you wish to provide *additional* directives to these
    specified directives, you must explicitly declare them. Example:

      MyAppSchema = GraphQLSchema(
          ...
          directives=specified_directives.extend([MyCustomerDirective]),
      )
    """
    __slots__ = '_query', '_mutation', '_subscription', '_type_map', '_directives', '_implementations', '_possible_type_map'

    def __init__(self, query, mutation=None, subscription=None, directives=None, types=None):
        assert isinstance(query, GraphQLObjectType), 'Schema query must be Object Type but got: {}.'.format(query)
        if mutation:
            assert isinstance(mutation, GraphQLObjectType), \
                'Schema mutation must be Object Type but got: {}.'.format(mutation)

        if subscription:
            assert isinstance(subscription, GraphQLObjectType), \
                'Schema subscription must be Object Type but got: {}.'.format(subscription)

        if types:
            assert isinstance(types, Iterable), \
                'Schema types must be iterable if provided but got: {}.'.format(types)

        self._query = query
        self._mutation = mutation
        self._subscription = subscription
        if directives is None:
            directives = specified_directives

        assert all(isinstance(d, GraphQLDirective) for d in directives), \
            'Schema directives must be List[GraphQLDirective] if provided but got: {}.'.format(
                directives
        )
        self._directives = directives

        initial_types = [
            query,
            mutation,
            subscription,
            IntrospectionSchema
        ]
        if types:
            initial_types += types
        self._type_map = GraphQLTypeMap(initial_types)

    def get_query_type(self):
        return self._query

    def get_mutation_type(self):
        return self._mutation

    def get_subscription_type(self):
        return self._subscription

    def get_type_map(self):
        return self._type_map

    def get_type(self, name):
        return self._type_map.get(name)

    def get_directives(self):
        return self._directives

    def get_directive(self, name):
        for directive in self.get_directives():
            if directive.name == name:
                return directive

        return None

    def get_possible_types(self, abstract_type):
        return self._type_map.get_possible_types(abstract_type)

    def is_possible_type(self, abstract_type, possible_type):
        return self._type_map.is_possible_type(abstract_type, possible_type)
