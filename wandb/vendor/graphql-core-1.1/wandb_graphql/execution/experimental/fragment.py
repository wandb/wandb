import functools

from wandb_promise import Promise, is_thenable, promise_for_dict

from ...pyutils.cached_property import cached_property
from ...pyutils.default_ordered_dict import DefaultOrderedDict
from ...type import (GraphQLInterfaceType, GraphQLList, GraphQLNonNull,
                     GraphQLObjectType, GraphQLUnionType)
from ..base import ResolveInfo, Undefined, collect_fields, get_field_def
from ..values import get_argument_values
from ...error import GraphQLError
try:
    from itertools import izip as zip
except:
    pass


def get_base_type(type):
    if isinstance(type, (GraphQLList, GraphQLNonNull)):
        return get_base_type(type.of_type)
    return type


def get_subfield_asts(context, return_type, field_asts):
    subfield_asts = DefaultOrderedDict(list)
    visited_fragment_names = set()
    for field_ast in field_asts:
        selection_set = field_ast.selection_set
        if selection_set:
            subfield_asts = collect_fields(
                context, return_type, selection_set,
                subfield_asts, visited_fragment_names
            )
    return subfield_asts


def get_resolvers(context, type, field_asts):
    from .resolver import field_resolver
    subfield_asts = get_subfield_asts(context, type, field_asts)

    for response_name, field_asts in subfield_asts.items():
        field_ast = field_asts[0]
        field_name = field_ast.name.value
        field_def = get_field_def(context and context.schema, type, field_name)
        if not field_def:
            continue
        field_base_type = get_base_type(field_def.type)
        field_fragment = None
        info = ResolveInfo(
            field_name,
            field_asts,
            field_base_type,
            parent_type=type,
            schema=context and context.schema,
            fragments=context and context.fragments,
            root_value=context and context.root_value,
            operation=context and context.operation,
            variable_values=context and context.variable_values,
        )
        if isinstance(field_base_type, GraphQLObjectType):
            field_fragment = Fragment(
                type=field_base_type,
                field_asts=field_asts,
                info=info,
                context=context
            )
        elif isinstance(field_base_type, (GraphQLInterfaceType, GraphQLUnionType)):
            field_fragment = AbstractFragment(
                abstract_type=field_base_type,
                field_asts=field_asts,
                info=info,
                context=context
            )
        resolver = field_resolver(field_def, exe_context=context, info=info, fragment=field_fragment)
        args = get_argument_values(
            field_def.args,
            field_ast.arguments,
            context and context.variable_values
        )
        yield (response_name, Field(resolver, args, context and context.context_value, info))


class Field(object):
    __slots__ = ('fn', 'args', 'context', 'info')

    def __init__(self, fn, args, context, info):
        self.fn = fn
        self.args = args
        self.context = context
        self.info = info

    def execute(self, root):
        return self.fn(root, self.args, self.context, self.info)


class Fragment(object):

    def __init__(self, type, field_asts, context=None, info=None):
        self.type = type
        self.field_asts = field_asts
        self.context = context
        self.info = info

    @cached_property
    def partial_resolvers(self):
        return list(get_resolvers(
            self.context,
            self.type,
            self.field_asts
        ))

    @cached_property
    def fragment_container(self):
        try:
            fields = next(zip(*self.partial_resolvers))
        except StopIteration:
            fields = tuple()

        class FragmentInstance(dict):
            # def __init__(self):
                # self.fields = fields
            # _fields = ('c','b','a')
            set = dict.__setitem__
            # def set(self, name, value):
            #     self[name] = value

            def __iter__(self):
                return iter(fields)

        return FragmentInstance

    def have_type(self, root):
        return not self.type.is_type_of or self.type.is_type_of(root, self.context.context_value, self.info)

    def resolve(self, root):
        if root and not self.have_type(root):
            raise GraphQLError(
                u'Expected value of type "{}" but got: {}.'.format(self.type, type(root).__name__),
                self.info.field_asts
            )

        contains_promise = False

        final_results = self.fragment_container()
        # return OrderedDict(
        #     ((field_name, field_resolver(root, field_args, context, info))
        #         for field_name, field_resolver, field_args, context, info in self.partial_resolvers)
        # )
        for response_name, field_resolver in self.partial_resolvers:

            result = field_resolver.execute(root)
            if result is Undefined:
                continue

            if not contains_promise and is_thenable(result):
                contains_promise = True

            final_results[response_name] = result

        if not contains_promise:
            return final_results

        return promise_for_dict(final_results)
        # return {
        #     field_name: field_resolver(root, field_args, context, info)
        #     for field_name, field_resolver, field_args, context, info in self.partial_resolvers
        # }

    def resolve_serially(self, root):
        def execute_field_callback(results, resolver):
            response_name, field_resolver = resolver

            result = field_resolver.execute(root)

            if result is Undefined:
                return results

            if is_thenable(result):
                def collect_result(resolved_result):
                    results[response_name] = resolved_result
                    return results

                return result.then(collect_result)

            results[response_name] = result
            return results

        def execute_field(prev_promise, resolver):
            return prev_promise.then(lambda results: execute_field_callback(results, resolver))

        return functools.reduce(execute_field, self.partial_resolvers, Promise.resolve(self.fragment_container()))

    def __eq__(self, other):
        return isinstance(other, Fragment) and (
            other.type == self.type and
            other.field_asts == self.field_asts and
            other.context == self.context and
            other.info == self.info
        )


class AbstractFragment(object):

    def __init__(self, abstract_type, field_asts, context=None, info=None):
        self.abstract_type = abstract_type
        self.field_asts = field_asts
        self.context = context
        self.info = info
        self._fragments = {}

    @cached_property
    def possible_types(self):
        return self.context.schema.get_possible_types(self.abstract_type)

    @cached_property
    def possible_types_with_is_type_of(self):
        return [
            (type, type.is_type_of) for type in self.possible_types if callable(type.is_type_of)
        ]

    def get_fragment(self, type):
        if isinstance(type, str):
            type = self.context.schema.get_type(type)

        if type not in self._fragments:
            assert type in self.possible_types, (
                'Runtime Object type "{}" is not a possible type for "{}".'
            ).format(type, self.abstract_type)
            self._fragments[type] = Fragment(
                type,
                self.field_asts,
                self.context,
                self.info
            )

        return self._fragments[type]

    def resolve_type(self, result):
        return_type = self.abstract_type
        context = self.context.context_value

        if return_type.resolve_type:
            return return_type.resolve_type(result, context, self.info)

        for type, is_type_of in self.possible_types_with_is_type_of:
            if is_type_of(result, context, self.info):
                return type

    def resolve(self, root):
        _type = self.resolve_type(root)
        fragment = self.get_fragment(_type)
        return fragment.resolve(root)
