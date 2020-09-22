import collections
import json

from six import string_types

from ..error import GraphQLError
from ..language.printer import print_ast
from ..type import (GraphQLEnumType, GraphQLInputObjectType, GraphQLList,
                    GraphQLNonNull, GraphQLScalarType, is_input_type)
from ..utils.is_valid_value import is_valid_value
from ..utils.type_from_ast import type_from_ast
from ..utils.value_from_ast import value_from_ast

__all__ = ['get_variable_values', 'get_argument_values']


def get_variable_values(schema, definition_asts, inputs):
    """Prepares an object map of variables of the correct type based on the provided variable definitions and arbitrary input.
    If the input cannot be parsed to match the variable definitions, a GraphQLError will be thrown."""
    if inputs is None:
        inputs = {}

    values = {}
    for def_ast in definition_asts:
        var_name = def_ast.variable.name.value
        value = get_variable_value(schema, def_ast, inputs.get(var_name))
        values[var_name] = value

    return values


def get_argument_values(arg_defs, arg_asts, variables=None):
    """Prepares an object map of argument values given a list of argument
    definitions and list of argument AST nodes."""
    if not arg_defs:
        return {}

    if arg_asts:
        arg_ast_map = {arg.name.value: arg for arg in arg_asts}
    else:
        arg_ast_map = {}

    result = {}
    for name, arg_def in arg_defs.items():
        value_ast = arg_ast_map.get(name)
        if value_ast:
            value_ast = value_ast.value

        value = value_from_ast(
            value_ast,
            arg_def.type,
            variables
        )

        if value is None:
            value = arg_def.default_value

        if value is not None:
            # We use out_name as the output name for the
            # dict if exists
            result[arg_def.out_name or name] = value

    return result


def get_variable_value(schema, definition_ast, input):
    """Given a variable definition, and any value of input, return a value which adheres to the variable definition,
    or throw an error."""
    type = type_from_ast(schema, definition_ast.type)
    variable = definition_ast.variable

    if not type or not is_input_type(type):
        raise GraphQLError(
            'Variable "${}" expected value of type "{}" which cannot be used as an input type.'.format(
                variable.name.value,
                print_ast(definition_ast.type),
            ),
            [definition_ast]
        )

    input_type = type
    errors = is_valid_value(input, input_type)
    if not errors:
        if input is None:
            default_value = definition_ast.default_value
            if default_value:
                return value_from_ast(default_value, input_type)

        return coerce_value(input_type, input)

    if input is None:
        raise GraphQLError(
            'Variable "${}" of required type "{}" was not provided.'.format(
                variable.name.value,
                print_ast(definition_ast.type)
            ),
            [definition_ast]
        )

    message = (u'\n' + u'\n'.join(errors)) if errors else u''
    raise GraphQLError(
        'Variable "${}" got invalid value {}.{}'.format(
            variable.name.value,
            json.dumps(input, sort_keys=True),
            message
        ),
        [definition_ast]
    )


def coerce_value(type, value):
    """Given a type and any value, return a runtime value coerced to match the type."""
    if isinstance(type, GraphQLNonNull):
        # Note: we're not checking that the result of coerceValue is
        # non-null.
        # We only call this function after calling isValidValue.
        return coerce_value(type.of_type, value)

    if value is None:
        return None

    if isinstance(type, GraphQLList):
        item_type = type.of_type
        if not isinstance(value, string_types) and isinstance(value, collections.Iterable):
            return [coerce_value(item_type, item) for item in value]
        else:
            return [coerce_value(item_type, value)]

    if isinstance(type, GraphQLInputObjectType):
        fields = type.fields
        obj = {}
        for field_name, field in fields.items():
            field_value = coerce_value(field.type, value.get(field_name))
            if field_value is None:
                field_value = field.default_value

            if field_value is not None:
                # We use out_name as the output name for the
                # dict if exists
                obj[field.out_name or field_name] = field_value

        return obj

    assert isinstance(type, (GraphQLScalarType, GraphQLEnumType)), \
        'Must be input type'

    return type.parse_value(value)
