from ...error import GraphQLError
from .base import ValidationRule


class NoUnusedFragments(ValidationRule):
    __slots__ = 'fragment_definitions', 'operation_definitions', 'fragment_adjacencies', 'spread_names'

    def __init__(self, context):
        super(NoUnusedFragments, self).__init__(context)
        self.operation_definitions = []
        self.fragment_definitions = []

    def enter_OperationDefinition(self, node, key, parent, path, ancestors):
        self.operation_definitions.append(node)
        return False

    def enter_FragmentDefinition(self, node, key, parent, path, ancestors):
        self.fragment_definitions.append(node)
        return False

    def leave_Document(self, node, key, parent, path, ancestors):
        fragment_names_used = set()

        for operation in self.operation_definitions:
            fragments = self.context.get_recursively_referenced_fragments(operation)
            for fragment in fragments:
                fragment_names_used.add(fragment.name.value)

        for fragment_definition in self.fragment_definitions:
            if fragment_definition.name.value not in fragment_names_used:
                self.context.report_error(GraphQLError(
                    self.unused_fragment_message(fragment_definition.name.value),
                    [fragment_definition]
                ))

    @staticmethod
    def unused_fragment_message(fragment_name):
        return 'Fragment "{}" is never used.'.format(fragment_name)
