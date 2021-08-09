from ..language.ast import (FragmentDefinition, FragmentSpread,
                            OperationDefinition)
from ..language.visitor import ParallelVisitor, TypeInfoVisitor, Visitor, visit
from ..type import GraphQLSchema
from ..utils.type_info import TypeInfo
from .rules import specified_rules


def validate(schema, ast, rules=specified_rules):
    assert schema, 'Must provide schema'
    assert ast, 'Must provide document'
    assert isinstance(schema, GraphQLSchema)
    type_info = TypeInfo(schema)
    return visit_using_rules(schema, type_info, ast, rules)


def visit_using_rules(schema, type_info, ast, rules):
    context = ValidationContext(schema, ast, type_info)
    visitors = [rule(context) for rule in rules]
    visit(ast, TypeInfoVisitor(type_info, ParallelVisitor(visitors)))
    return context.get_errors()


class VariableUsage(object):
    __slots__ = 'node', 'type'

    def __init__(self, node, type):
        self.node = node
        self.type = type


class UsageVisitor(Visitor):
    __slots__ = 'usages', 'type_info'

    def __init__(self, usages, type_info):
        self.usages = usages
        self.type_info = type_info

    def enter_VariableDefinition(self, node, key, parent, path, ancestors):
        return False

    def enter_Variable(self, node, key, parent, path, ancestors):
        usage = VariableUsage(node, type=self.type_info.get_input_type())
        self.usages.append(usage)


class ValidationContext(object):
    __slots__ = ('_schema', '_ast', '_type_info', '_errors', '_fragments', '_fragment_spreads',
                 '_recursively_referenced_fragments', '_variable_usages', '_recursive_variable_usages')

    def __init__(self, schema, ast, type_info):
        self._schema = schema
        self._ast = ast
        self._type_info = type_info
        self._errors = []
        self._fragments = None
        self._fragment_spreads = {}
        self._recursively_referenced_fragments = {}
        self._variable_usages = {}
        self._recursive_variable_usages = {}

    def report_error(self, error):
        self._errors.append(error)

    def get_errors(self):
        return self._errors

    def get_schema(self):
        return self._schema

    def get_variable_usages(self, node):
        usages = self._variable_usages.get(node)
        if usages is None:
            usages = []
            sub_visitor = UsageVisitor(usages, self._type_info)
            visit(node, TypeInfoVisitor(self._type_info, sub_visitor))
            self._variable_usages[node] = usages

        return usages

    def get_recursive_variable_usages(self, operation):
        assert isinstance(operation, OperationDefinition)
        usages = self._recursive_variable_usages.get(operation)
        if usages is None:
            usages = self.get_variable_usages(operation)
            fragments = self.get_recursively_referenced_fragments(operation)
            for fragment in fragments:
                usages.extend(self.get_variable_usages(fragment))
            self._recursive_variable_usages[operation] = usages

        return usages

    def get_recursively_referenced_fragments(self, operation):
        assert isinstance(operation, OperationDefinition)
        fragments = self._recursively_referenced_fragments.get(operation)
        if not fragments:
            fragments = []
            collected_names = set()
            nodes_to_visit = [operation.selection_set]
            while nodes_to_visit:
                node = nodes_to_visit.pop()
                spreads = self.get_fragment_spreads(node)
                for spread in spreads:
                    frag_name = spread.name.value
                    if frag_name not in collected_names:
                        collected_names.add(frag_name)
                        fragment = self.get_fragment(frag_name)
                        if fragment:
                            fragments.append(fragment)
                            nodes_to_visit.append(fragment.selection_set)
            self._recursively_referenced_fragments[operation] = fragments
        return fragments

    def get_fragment_spreads(self, node):
        spreads = self._fragment_spreads.get(node)
        if not spreads:
            spreads = []
            sets_to_visit = [node]
            while sets_to_visit:
                _set = sets_to_visit.pop()
                for selection in _set.selections:
                    if isinstance(selection, FragmentSpread):
                        spreads.append(selection)
                    elif selection.selection_set:
                        sets_to_visit.append(selection.selection_set)

            self._fragment_spreads[node] = spreads
        return spreads

    def get_ast(self):
        return self._ast

    def get_fragment(self, name):
        fragments = self._fragments
        if fragments is None:
            self._fragments = fragments = {}
            for statement in self.get_ast().definitions:
                if isinstance(statement, FragmentDefinition):
                    fragments[statement.name.value] = statement
        return fragments.get(name)

    def get_type(self):
        return self._type_info.get_type()

    def get_parent_type(self):
        return self._type_info.get_parent_type()

    def get_input_type(self):
        return self._type_info.get_input_type()

    def get_field_def(self):
        return self._type_info.get_field_def()

    def get_directive(self):
        return self._type_info.get_directive()

    def get_argument(self):
        return self._type_info.get_argument()
