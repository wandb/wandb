import sys
import collections
from functools import partial

from promise import Promise, is_thenable

from ...error import GraphQLError, GraphQLLocatedError
from ...type import (GraphQLEnumType, GraphQLInterfaceType, GraphQLList,
                     GraphQLNonNull, GraphQLObjectType, GraphQLScalarType,
                     GraphQLUnionType)
from ..base import default_resolve_fn
from ...execution import executor
from .utils import imap, normal_map


def on_complete_resolver(on_error, __func, exe_context, info, __resolver, *args, **kwargs):
    try:
        result = __resolver(*args, **kwargs)
        if isinstance(result, Exception):
            return on_error(result)
        # return Promise.resolve(result).then(__func).catch(on_error)
        if is_thenable(result):
            # TODO: Remove this, if a promise is resolved with an Exception,
            # it should raise by default. This is fixing an old behavior
            # in the Promise package
            def on_resolve(value):
                if isinstance(value, Exception):
                    return on_error(value)
                return value
            return result.then(on_resolve).then(__func).catch(on_error)
        return __func(result)
    except Exception as e:
        return on_error(e)


def complete_list_value(inner_resolver, exe_context, info, on_error, result):
    if result is None:
        return None

    assert isinstance(result, collections.Iterable), \
        ('User Error: expected iterable, but did not find one ' +
         'for field {}.{}.').format(info.parent_type, info.field_name)

    completed_results = normal_map(inner_resolver, result)

    if not any(imap(is_thenable, completed_results)):
        return completed_results

    return Promise.all(completed_results).catch(on_error)


def complete_nonnull_value(exe_context, info, result):
    if result is None:
        raise GraphQLError(
            'Cannot return null for non-nullable field {}.{}.'.format(info.parent_type, info.field_name),
            info.field_asts
        )
    return result


def complete_leaf_value(serialize, result):
    if result is None:
        return None
    return serialize(result)


def complete_object_value(fragment_resolve, exe_context, on_error, result):
    if result is None:
        return None

    result = fragment_resolve(result)
    if is_thenable(result):
        return result.catch(on_error)
    return result


def field_resolver(field, fragment=None, exe_context=None, info=None):
    # resolver = exe_context.get_field_resolver(field.resolver or default_resolve_fn)
    resolver = field.resolver or default_resolve_fn
    if exe_context:
        # We decorate the resolver with the middleware
        resolver = exe_context.get_field_resolver(resolver)
    return type_resolver(field.type, resolver,
                         fragment, exe_context, info, catch_error=True)


def type_resolver(return_type, resolver, fragment=None, exe_context=None, info=None, catch_error=False):
    if isinstance(return_type, GraphQLNonNull):
        return type_resolver_non_null(return_type, resolver, fragment, exe_context, info)

    if isinstance(return_type, (GraphQLScalarType, GraphQLEnumType)):
        return type_resolver_leaf(return_type, resolver, exe_context, info, catch_error)

    if isinstance(return_type, (GraphQLList)):
        return type_resolver_list(return_type, resolver, fragment, exe_context, info, catch_error)

    if isinstance(return_type, (GraphQLObjectType)):
        assert fragment and fragment.type == return_type, 'Fragment and return_type dont match'
        return type_resolver_fragment(return_type, resolver, fragment, exe_context, info, catch_error)

    if isinstance(return_type, (GraphQLInterfaceType, GraphQLUnionType)):
        assert fragment, 'You need to pass a fragment to resolve a Interface or Union'
        return type_resolver_fragment(return_type, resolver, fragment, exe_context, info, catch_error)

    raise Exception("The resolver have to be created for a fragment")


def on_error(exe_context, info, catch_error, e):
    error = e
    if not isinstance(e, (GraphQLLocatedError, GraphQLError)):
        error = GraphQLLocatedError(info.field_asts, original_error=e)
    if catch_error:
        exe_context.errors.append(error)
        executor.logger.exception("An error occurred while resolving field {}.{}".format(
            info.parent_type.name, info.field_name
        ))
        error.stack = sys.exc_info()[2]
        return None
    raise error


def type_resolver_fragment(return_type, resolver, fragment, exe_context, info, catch_error):
    on_complete_type_error = partial(on_error, exe_context, info, catch_error)
    complete_object_value_resolve = partial(
        complete_object_value,
        fragment.resolve,
        exe_context,
        on_complete_type_error)
    on_resolve_error = partial(on_error, exe_context, info, catch_error)
    return partial(on_complete_resolver, on_resolve_error, complete_object_value_resolve, exe_context, info, resolver)


def type_resolver_non_null(return_type, resolver, fragment, exe_context, info):  # no catch_error
    resolver = type_resolver(return_type.of_type, resolver, fragment, exe_context, info)
    nonnull_complete = partial(complete_nonnull_value, exe_context, info)
    on_resolve_error = partial(on_error, exe_context, info, False)
    return partial(on_complete_resolver, on_resolve_error, nonnull_complete, exe_context, info, resolver)


def type_resolver_leaf(return_type, resolver, exe_context, info, catch_error):
    leaf_complete = partial(complete_leaf_value, return_type.serialize)
    on_resolve_error = partial(on_error, exe_context, info, catch_error)
    return partial(on_complete_resolver, on_resolve_error, leaf_complete, exe_context, info, resolver)


def type_resolver_list(return_type, resolver, fragment, exe_context, info, catch_error):
    item_type = return_type.of_type
    inner_resolver = type_resolver(item_type, lambda item: item, fragment, exe_context, info, catch_error=True)
    on_resolve_error = partial(on_error, exe_context, info, catch_error)
    list_complete = partial(complete_list_value, inner_resolver, exe_context, info, on_resolve_error)
    return partial(on_complete_resolver, on_resolve_error, list_complete, exe_context, info, resolver)
