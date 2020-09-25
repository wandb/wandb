from .execution import ExecutionResult, execute
from .language.ast import Document
from .language.parser import parse
from .language.source import Source
from .validation import validate


# This is the primary entry point function for fulfilling GraphQL operations
# by parsing, validating, and executing a GraphQL document along side a
# GraphQL schema.

# More sophisticated GraphQL servers, such as those which persist queries,
# may wish to separate the validation and execution phases to a static time
# tooling step, and a server runtime step.

# schema:
#    The GraphQL type system to use when validating and executing a query.
# requestString:
#    A GraphQL language formatted string representing the requested operation.
# rootValue:
#    The value provided as the first argument to resolver functions on the top
#    level type (e.g. the query object type).
# variableValues:
#    A mapping of variable name to runtime value to use for all variables
#    defined in the requestString.
# operationName:
#    The name of the operation to use if requestString contains multiple
#    possible operations. Can be omitted if requestString contains only
#    one operation.
def graphql(schema, request_string='', root_value=None, context_value=None,
            variable_values=None, operation_name=None, executor=None,
            return_promise=False, middleware=None):
    try:
        if isinstance(request_string, Document):
            ast = request_string
        else:
            source = Source(request_string, 'GraphQL request')
            ast = parse(source)
        validation_errors = validate(schema, ast)
        if validation_errors:
            return ExecutionResult(
                errors=validation_errors,
                invalid=True,
            )
        return execute(
            schema,
            ast,
            root_value,
            context_value,
            operation_name=operation_name,
            variable_values=variable_values or {},
            executor=executor,
            return_promise=return_promise,
            middleware=middleware,
        )
    except Exception as e:
        return ExecutionResult(
            errors=[e],
            invalid=True,
        )
