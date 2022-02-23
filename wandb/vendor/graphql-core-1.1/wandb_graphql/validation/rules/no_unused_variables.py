from ...error import GraphQLError
from .base import ValidationRule


class NoUnusedVariables(ValidationRule):
    __slots__ = 'variable_definitions'

    def __init__(self, context):
        self.variable_definitions = []
        super(NoUnusedVariables, self).__init__(context)

    def enter_OperationDefinition(self, node, key, parent, path, ancestors):
        self.variable_definitions = []

    def leave_OperationDefinition(self, operation, key, parent, path, ancestors):
        variable_name_used = set()
        usages = self.context.get_recursive_variable_usages(operation)
        op_name = operation.name and operation.name.value or None

        for variable_usage in usages:
            variable_name_used.add(variable_usage.node.name.value)

        for variable_definition in self.variable_definitions:
            if variable_definition.variable.name.value not in variable_name_used:
                self.context.report_error(GraphQLError(
                    self.unused_variable_message(variable_definition.variable.name.value, op_name),
                    [variable_definition]
                ))

    def enter_VariableDefinition(self, node, key, parent, path, ancestors):
        self.variable_definitions.append(node)

    @staticmethod
    def unused_variable_message(variable_name, op_name):
        if op_name:
            return 'Variable "${}" is never used in operation "{}".'.format(variable_name, op_name)
        return 'Variable "${}" is never used.'.format(variable_name)
