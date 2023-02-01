from ...error import GraphQLError
from ...language.printer import print_ast
from ...type.definition import is_composite_type
from .base import ValidationRule


class FragmentsOnCompositeTypes(ValidationRule):

    def enter_InlineFragment(self, node, key, parent, path, ancestors):
        type = self.context.get_type()

        if node.type_condition and type and not is_composite_type(type):
            self.context.report_error(GraphQLError(
                self.inline_fragment_on_non_composite_error_message(print_ast(node.type_condition)),
                [node.type_condition]
            ))

    def enter_FragmentDefinition(self, node, key, parent, path, ancestors):
        type = self.context.get_type()

        if type and not is_composite_type(type):
            self.context.report_error(GraphQLError(
                self.fragment_on_non_composite_error_message(node.name.value, print_ast(node.type_condition)),
                [node.type_condition]
            ))

    @staticmethod
    def inline_fragment_on_non_composite_error_message(type):
        return 'Fragment cannot condition on non composite type "{}".'.format(type)

    @staticmethod
    def fragment_on_non_composite_error_message(frag_name, type):
        return 'Fragment "{}" cannot condition on non composite type "{}".'.format(frag_name, type)
