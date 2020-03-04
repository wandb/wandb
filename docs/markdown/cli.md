---
description: wandb.cli
---

# wandb.cli
[source](https://github.com/wandb/client/blob/master/wandb/cli.py#L0)


## cli.cli
```python
RunGroup.__call__(*args, **kwargs)
```
Alias for :meth:`main`.

### cli.add_help_option
bool(x) -> bool

Returns True when the argument x is true, False otherwise.
The builtins True and False are the only two instances of the class bool.
The class bool is a subclass of the class int, and cannot be subclassed.

### cli.chain
bool(x) -> bool

Returns True when the argument x is true, False otherwise.
The builtins True and False are the only two instances of the class bool.
The class bool is a subclass of the class int, and cannot be subclassed.

### cli.commands
dict() -> new empty dictionary
dict(mapping) -> new dictionary initialized from a mapping object's
(key, value) pairs
dict(iterable) -> new dictionary initialized as if via:
d = {}
for k, v in iterable:
d[k] = v
dict(**kwargs) -> new dictionary initialized with the name=value pairs
in the keyword argument list.  For example:  dict(one=1, two=2)

### cli.context_settings
dict() -> new empty dictionary
dict(mapping) -> new dictionary initialized from a mapping object's
(key, value) pairs
dict(iterable) -> new dictionary initialized as if via:
d = {}
for k, v in iterable:
d[k] = v
dict(**kwargs) -> new dictionary initialized with the name=value pairs
in the keyword argument list.  For example:  dict(one=1, two=2)

### cli.deprecated
bool(x) -> bool

Returns True when the argument x is true, False otherwise.
The builtins True and False are the only two instances of the class bool.
The class bool is a subclass of the class int, and cannot be subclassed.

### cli.help
str(object='') -> str
str(bytes_or_buffer[, encoding[, errors]]) -> str

Create a new string object from the given object. If encoding or
errors is specified, then the object must expose a data buffer
that will be decoded using the given encoding and error handler.
Otherwise, returns the result of object.__str__() (if defined)
or repr(object).
encoding defaults to sys.getdefaultencoding().
errors defaults to 'strict'.

### cli.hidden
bool(x) -> bool

Returns True when the argument x is true, False otherwise.
The builtins True and False are the only two instances of the class bool.
The class bool is a subclass of the class int, and cannot be subclassed.

### cli.invoke_without_command
bool(x) -> bool

Returns True when the argument x is true, False otherwise.
The builtins True and False are the only two instances of the class bool.
The class bool is a subclass of the class int, and cannot be subclassed.

### cli.name
str(object='') -> str
str(bytes_or_buffer[, encoding[, errors]]) -> str

Create a new string object from the given object. If encoding or
errors is specified, then the object must expose a data buffer
that will be decoded using the given encoding and error handler.
Otherwise, returns the result of object.__str__() (if defined)
or repr(object).
encoding defaults to sys.getdefaultencoding().
errors defaults to 'strict'.

### cli.no_args_is_help
bool(x) -> bool

Returns True when the argument x is true, False otherwise.
The builtins True and False are the only two instances of the class bool.
The class bool is a subclass of the class int, and cannot be subclassed.

### cli.options_metavar
str(object='') -> str
str(bytes_or_buffer[, encoding[, errors]]) -> str

Create a new string object from the given object. If encoding or
errors is specified, then the object must expose a data buffer
that will be decoded using the given encoding and error handler.
Otherwise, returns the result of object.__str__() (if defined)
or repr(object).
encoding defaults to sys.getdefaultencoding().
errors defaults to 'strict'.

### cli.params
Built-in mutable sequence.

If no argument is given, the constructor creates a new empty list.
The argument must be an iterable if specified.

### cli.subcommand_metavar
str(object='') -> str
str(bytes_or_buffer[, encoding[, errors]]) -> str

Create a new string object from the given object. If encoding or
errors is specified, then the object must expose a data buffer
that will be decoded using the given encoding and error handler.
Otherwise, returns the result of object.__str__() (if defined)
or repr(object).
encoding defaults to sys.getdefaultencoding().
errors defaults to 'strict'.

### cli
[source](https://github.com/wandb/client/blob/master/wandb/cli.py#L227)
```python
cli(ctx)
```
Weights & Biases.

Run "wandb docs" for full documentation.


## CallbackHandler
[source](https://github.com/wandb/client/blob/master/wandb/cli.py#L77)
```python
CallbackHandler(request, client_address, server)
```
Simple callback handler that stores query string parameters and shuts down the server.


## LocalServer
[source](https://github.com/wandb/client/blob/master/wandb/cli.py#L94)
```python
LocalServer()
```
A local HTTP server that finds an open port and listens for a callback. The urlencoded callback url is accessed via `.qs` the query parameters passed to the callback are accessed via `.result`


## cli.display_error
[source](https://github.com/wandb/client/blob/master/wandb/cli.py#L149)
```python
display_error(func)
```
Function decorator for catching common errors and re-raising as wandb.Error

## cli.prompt_for_project
[source](https://github.com/wandb/client/blob/master/wandb/cli.py#L166)
```python
prompt_for_project(ctx, entity)
```
Ask the user for a project, creating one if necessary.
