from ...error import GraphQLError
from .base import ValidationRule


class UniqueVariableNames(ValidationRule):
    __slots__ = 'known_variable_names',

    def __init__(self, context):
        super(UniqueVariableNames, self).__init__(context)
        self.known_variable_names = {}

    def enter_OperationDefinition(self, node, key, parent, path, ancestors):
        self.known_variable_names = {}

    def enter_VariableDefinition(self, node, key, parent, path, ancestors):
        variable_name = node.variable.name.value
        if variable_name in self.known_variable_names:
            self.context.report_error(GraphQLError(
                self.duplicate_variable_message(variable_name),
                [self.known_variable_names[variable_name], node.variable.name]
            ))
        else:
            self.known_variable_names[variable_name] = node.variable.name

    @staticmethod
    def duplicate_variable_message(operation_name):
        return 'There can be only one variable named "{}".'.format(operation_name)
