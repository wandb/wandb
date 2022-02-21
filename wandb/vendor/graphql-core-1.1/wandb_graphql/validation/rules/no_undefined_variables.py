from ...error import GraphQLError
from .base import ValidationRule


class NoUndefinedVariables(ValidationRule):
    __slots__ = 'defined_variable_names',

    def __init__(self, context):
        self.defined_variable_names = set()
        super(NoUndefinedVariables, self).__init__(context)

    @staticmethod
    def undefined_var_message(var_name, op_name=None):
        if op_name:
            return 'Variable "${}" is not defined by operation "{}".'.format(
                var_name, op_name
            )
        return 'Variable "${}" is not defined.'.format(var_name)

    def enter_OperationDefinition(self, operation, key, parent, path, ancestors):
        self.defined_variable_names = set()

    def leave_OperationDefinition(self, operation, key, parent, path, ancestors):
        usages = self.context.get_recursive_variable_usages(operation)

        for variable_usage in usages:
            node = variable_usage.node
            var_name = node.name.value
            if var_name not in self.defined_variable_names:
                self.context.report_error(GraphQLError(
                    self.undefined_var_message(var_name, operation.name and operation.name.value),
                    [node, operation]
                ))

    def enter_VariableDefinition(self, node, key, parent, path, ancestors):
        self.defined_variable_names.add(node.variable.name.value)
