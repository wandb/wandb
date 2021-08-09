import six

from ..language import visitor_meta
from ..type.definition import (GraphQLInputObjectType, GraphQLList,
                               get_named_type, get_nullable_type,
                               is_composite_type)
from .get_field_def import get_field_def
from .type_from_ast import type_from_ast


def pop(lst):
    if lst:
        lst.pop()


# noinspection PyPep8Naming
@six.add_metaclass(visitor_meta.VisitorMeta)
class TypeInfo(object):
    __slots__ = '_schema', '_type_stack', '_parent_type_stack', '_input_type_stack', '_field_def_stack', '_directive', \
                '_argument', '_get_field_def_fn'

    def __init__(self, schema, get_field_def_fn=get_field_def):
        self._schema = schema
        self._type_stack = []
        self._parent_type_stack = []
        self._input_type_stack = []
        self._field_def_stack = []
        self._directive = None
        self._argument = None
        self._get_field_def_fn = get_field_def_fn

    def get_type(self):
        if self._type_stack:
            return self._type_stack[-1]

    def get_parent_type(self):
        if self._parent_type_stack:
            return self._parent_type_stack[-1]

    def get_input_type(self):
        if self._input_type_stack:
            return self._input_type_stack[-1]

    def get_field_def(self):
        if self._field_def_stack:
            return self._field_def_stack[-1]

    def get_directive(self):
        return self._directive

    def get_argument(self):
        return self._argument

    def leave(self, node):
        method = self._get_leave_handler(type(node))
        if method:
            return method(self)

    def enter(self, node):
        method = self._get_enter_handler(type(node))
        if method:
            return method(self, node)

    def enter_SelectionSet(self, node):
        named_type = get_named_type(self.get_type())
        composite_type = None
        if is_composite_type(named_type):
            composite_type = named_type
        self._parent_type_stack.append(composite_type)

    def enter_Field(self, node):
        parent_type = self.get_parent_type()
        field_def = None
        if parent_type:
            field_def = self._get_field_def_fn(self._schema, parent_type, node)
        self._field_def_stack.append(field_def)
        self._type_stack.append(field_def and field_def.type)

    def enter_Directive(self, node):
        self._directive = self._schema.get_directive(node.name.value)

    def enter_OperationDefinition(self, node):
        definition_type = None
        if node.operation == 'query':
            definition_type = self._schema.get_query_type()
        elif node.operation == 'mutation':
            definition_type = self._schema.get_mutation_type()

        self._type_stack.append(definition_type)

    def enter_InlineFragment(self, node):
        type_condition_ast = node.type_condition
        type = type_from_ast(self._schema, type_condition_ast) if type_condition_ast else self.get_type()
        self._type_stack.append(type)

    enter_FragmentDefinition = enter_InlineFragment

    def enter_VariableDefinition(self, node):
        self._input_type_stack.append(type_from_ast(self._schema, node.type))

    def enter_Argument(self, node):
        arg_def = None
        arg_type = None
        field_or_directive = self.get_directive() or self.get_field_def()
        if field_or_directive:
            arg_def = field_or_directive.args.get(node.name.value)
            if arg_def:
                arg_type = arg_def.type
        self._argument = arg_def
        self._input_type_stack.append(arg_type)

    def enter_ListValue(self, node):
        list_type = get_nullable_type(self.get_input_type())
        self._input_type_stack.append(
            list_type.of_type if isinstance(list_type, GraphQLList) else None
        )

    def enter_ObjectField(self, node):
        object_type = get_named_type(self.get_input_type())
        field_type = None
        if isinstance(object_type, GraphQLInputObjectType):
            input_field = object_type.fields.get(node.name.value)
            field_type = input_field.type if input_field else None
        self._input_type_stack.append(field_type)

    def leave_SelectionSet(self):
        pop(self._parent_type_stack)

    def leave_Field(self):
        pop(self._field_def_stack)
        pop(self._type_stack)

    def leave_Directive(self):
        self._directive = None

    def leave_OperationDefinition(self):
        pop(self._type_stack)

    leave_InlineFragment = leave_OperationDefinition
    leave_FragmentDefinition = leave_OperationDefinition

    def leave_VariableDefinition(self):
        pop(self._input_type_stack)

    def leave_Argument(self):
        self._argument = None
        pop(self._input_type_stack)

    def leave_ListType(self):
        pop(self._input_type_stack)

    leave_ObjectField = leave_ListType
