from ...error import GraphQLError
from .base import ValidationRule


class UniqueArgumentNames(ValidationRule):
    __slots__ = 'known_arg_names',

    def __init__(self, context):
        super(UniqueArgumentNames, self).__init__(context)
        self.known_arg_names = {}

    def enter_Field(self, node, key, parent, path, ancestors):
        self.known_arg_names = {}

    def enter_Directive(self, node, key, parent, path, ancestors):
        self.known_arg_names = {}

    def enter_Argument(self, node, key, parent, path, ancestors):
        arg_name = node.name.value

        if arg_name in self.known_arg_names:
            self.context.report_error(GraphQLError(
                self.duplicate_arg_message(arg_name),
                [self.known_arg_names[arg_name], node.name]
            ))
        else:
            self.known_arg_names[arg_name] = node.name
        return False

    @staticmethod
    def duplicate_arg_message(field):
        return 'There can only be one argument named "{}".'.format(field)
