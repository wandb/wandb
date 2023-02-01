import json

from .visitor import Visitor, visit

__all__ = ['print_ast']


def print_ast(ast):
    return visit(ast, PrintingVisitor())


class PrintingVisitor(Visitor):
    __slots__ = ()

    def leave_Name(self, node, *args):
        return node.value

    def leave_Variable(self, node, *args):
        return '$' + node.name

    def leave_Document(self, node, *args):
        return join(node.definitions, '\n\n') + '\n'

    def leave_OperationDefinition(self, node, *args):
        name = node.name
        selection_set = node.selection_set
        op = node.operation
        var_defs = wrap('(', join(node.variable_definitions, ', '), ')')
        directives = join(node.directives, ' ')

        if not name and not directives and not var_defs and op == 'query':
            return selection_set

        return join([op, join([name, var_defs]), directives, selection_set], ' ')

    def leave_VariableDefinition(self, node, *args):
        return node.variable + ': ' + node.type + wrap(' = ', node.default_value)

    def leave_SelectionSet(self, node, *args):
        return block(node.selections)

    def leave_Field(self, node, *args):
        return join([
            wrap('', node.alias, ': ') + node.name + wrap('(', join(node.arguments, ', '), ')'),
            join(node.directives, ' '),
            node.selection_set
        ], ' ')

    def leave_Argument(self, node, *args):
        return node.name + ': ' + node.value

    # Fragments

    def leave_FragmentSpread(self, node, *args):
        return '...' + node.name + wrap(' ', join(node.directives, ' '))

    def leave_InlineFragment(self, node, *args):
        return join([
            '...',
            wrap('on ', node.type_condition),
            join(node.directives, ''),
            node.selection_set
        ], ' ')

    def leave_FragmentDefinition(self, node, *args):
        return ('fragment {} on {} '.format(node.name, node.type_condition) +
                wrap('', join(node.directives, ' '), ' ') +
                node.selection_set)

    # Value

    def leave_IntValue(self, node, *args):
        return node.value

    def leave_FloatValue(self, node, *args):
        return node.value

    def leave_StringValue(self, node, *args):
        return json.dumps(node.value)

    def leave_BooleanValue(self, node, *args):
        return json.dumps(node.value)

    def leave_EnumValue(self, node, *args):
        return node.value

    def leave_ListValue(self, node, *args):
        return '[' + join(node.values, ', ') + ']'

    def leave_ObjectValue(self, node, *args):
        return '{' + join(node.fields, ', ') + '}'

    def leave_ObjectField(self, node, *args):
        return node.name + ': ' + node.value

    # Directive

    def leave_Directive(self, node, *args):
        return '@' + node.name + wrap('(', join(node.arguments, ', '), ')')

    # Type

    def leave_NamedType(self, node, *args):
        return node.name

    def leave_ListType(self, node, *args):
        return '[' + node.type + ']'

    def leave_NonNullType(self, node, *args):
        return node.type + '!'

    # Type Definitions:

    def leave_SchemaDefinition(self, node, *args):
        return join([
            'schema',
            join(node.directives, ' '),
            block(node.operation_types),
            ], ' ')

    def leave_OperationTypeDefinition(self, node, *args):
        return '{}: {}'.format(node.operation, node.type)

    def leave_ScalarTypeDefinition(self, node, *args):
        return 'scalar ' + node.name + wrap(' ', join(node.directives, ' '))

    def leave_ObjectTypeDefinition(self, node, *args):
        return join([
            'type',
            node.name,
            wrap('implements ', join(node.interfaces, ', ')),
            join(node.directives, ' '),
            block(node.fields)
        ], ' ')

    def leave_FieldDefinition(self, node, *args):
        return (
            node.name +
            wrap('(', join(node.arguments, ', '), ')') +
            ': ' +
            node.type +
            wrap(' ', join(node.directives, ' '))
        )

    def leave_InputValueDefinition(self, node, *args):
        return node.name + ': ' + node.type + wrap(' = ', node.default_value) + wrap(' ', join(node.directives, ' '))

    def leave_InterfaceTypeDefinition(self, node, *args):
        return 'interface ' + node.name + wrap(' ', join(node.directives, ' ')) + ' ' + block(node.fields)

    def leave_UnionTypeDefinition(self, node, *args):
        return 'union ' + node.name + wrap(' ', join(node.directives, ' ')) + ' = ' + join(node.types, ' | ')

    def leave_EnumTypeDefinition(self, node, *args):
        return 'enum ' + node.name + wrap(' ', join(node.directives, ' ')) + ' ' + block(node.values)

    def leave_EnumValueDefinition(self, node, *args):
        return node.name + wrap(' ', join(node.directives, ' '))

    def leave_InputObjectTypeDefinition(self, node, *args):
        return 'input ' + node.name + wrap(' ', join(node.directives, ' ')) + ' ' + block(node.fields)

    def leave_TypeExtensionDefinition(self, node, *args):
        return 'extend ' + node.definition

    def leave_DirectiveDefinition(self, node, *args):
        return 'directive @{}{} on {}'.format(node.name, wrap(
            '(', join(node.arguments, ', '), ')'), ' | '.join(node.locations))


def join(maybe_list, separator=''):
    if maybe_list:
        return separator.join(filter(None, maybe_list))
    return ''


def block(_list):
    '''Given a list, print each item on its own line, wrapped in an indented "{ }" block.'''
    if _list:
        return indent('{\n' + join(_list, '\n')) + '\n}'
    return '{}'


def wrap(start, maybe_str, end=''):
    if maybe_str:
        return start + maybe_str + end
    return ''


def indent(maybe_str):
    if maybe_str:
        return maybe_str.replace('\n', '\n  ')
    return maybe_str
