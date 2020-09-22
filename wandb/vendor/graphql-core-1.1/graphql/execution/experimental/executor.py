from promise import Promise

from ...type import GraphQLSchema
from ..base import ExecutionContext, ExecutionResult, get_operation_root_type
from ..executors.sync import SyncExecutor
from ..middleware import MiddlewareManager
from .fragment import Fragment


def execute(schema, document_ast, root_value=None, context_value=None,
            variable_values=None, operation_name=None, executor=None,
            return_promise=False, middleware=None):
    assert schema, 'Must provide schema'
    assert isinstance(schema, GraphQLSchema), (
        'Schema must be an instance of GraphQLSchema. Also ensure that there are ' +
        'not multiple versions of GraphQL installed in your node_modules directory.'
    )
    if middleware:
        if not isinstance(middleware, MiddlewareManager):
            middleware = MiddlewareManager(*middleware)
        assert isinstance(middleware, MiddlewareManager), (
            'middlewares have to be an instance'
            ' of MiddlewareManager. Received "{}".'.format(middleware)
        )

    if executor is None:
        executor = SyncExecutor()

    context = ExecutionContext(
        schema,
        document_ast,
        root_value,
        context_value,
        variable_values,
        operation_name,
        executor,
        middleware
    )

    def executor(resolve, reject):
        return resolve(execute_operation(context, context.operation, root_value))

    def on_rejected(error):
        context.errors.append(error)
        return None

    def on_resolve(data):
        if not context.errors:
            return ExecutionResult(data=data)
        return ExecutionResult(data=data, errors=context.errors)

    promise = Promise(executor).catch(on_rejected).then(on_resolve)
    if return_promise:
        return promise
    context.executor.wait_until_finished()
    return promise.get()


def execute_operation(exe_context, operation, root_value):
    type = get_operation_root_type(exe_context.schema, operation)
    execute_serially = operation.operation == 'mutation'

    fragment = Fragment(type=type, field_asts=[operation], context=exe_context)
    if execute_serially:
        return fragment.resolve_serially(root_value)
    return fragment.resolve(root_value)
