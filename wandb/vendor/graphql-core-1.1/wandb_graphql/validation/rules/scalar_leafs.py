from ...error import GraphQLError
from ...type.definition import get_named_type, is_leaf_type
from .base import ValidationRule


class ScalarLeafs(ValidationRule):

    def enter_Field(self, node, key, parent, path, ancestors):
        type = self.context.get_type()

        if not type:
            return

        if is_leaf_type(get_named_type(type)):
            if node.selection_set:
                self.context.report_error(GraphQLError(
                    self.no_subselection_allowed_message(node.name.value, type),
                    [node.selection_set]
                ))

        elif not node.selection_set:
            self.context.report_error(GraphQLError(
                self.required_subselection_message(node.name.value, type),
                [node]
            ))

    @staticmethod
    def no_subselection_allowed_message(field, type):
        return 'Field "{}" of type "{}" must not have a sub selection.'.format(field, type)

    @staticmethod
    def required_subselection_message(field, type):
        return 'Field "{}" of type "{}" must have a sub selection.'.format(field, type)
