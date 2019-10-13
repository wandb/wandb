
# [wandb.cli](https://github.com/wandb/client/blob/feature/docs/wandb/cli.py#L0)


## cli
```python
RunGroup.__call__(*args, **kwargs)
```
Alias for :meth:`main`.

### add_help_option
bool(x) -> bool

Returns True when the argument x is true, False otherwise.
The builtins True and False are the only two instances of the class bool.
The class bool is a subclass of the class int, and cannot be subclassed.

### chain
bool(x) -> bool

Returns True when the argument x is true, False otherwise.
The builtins True and False are the only two instances of the class bool.
The class bool is a subclass of the class int, and cannot be subclassed.

### commands
dict() -> new empty dictionary
dict(mapping) -> new dictionary initialized from a mapping object's
(key, value) pairs
dict(iterable) -> new dictionary initialized as if via:
d = {}
for k, v in iterable:
d[k] = v
dict(**kwargs) -> new dictionary initialized with the name=value pairs
in the keyword argument list.  For example:  dict(one=1, two=2)

### context_settings
dict() -> new empty dictionary
dict(mapping) -> new dictionary initialized from a mapping object's
(key, value) pairs
dict(iterable) -> new dictionary initialized as if via:
d = {}
for k, v in iterable:
d[k] = v
dict(**kwargs) -> new dictionary initialized with the name=value pairs
in the keyword argument list.  For example:  dict(one=1, two=2)

### deprecated
bool(x) -> bool

Returns True when the argument x is true, False otherwise.
The builtins True and False are the only two instances of the class bool.
The class bool is a subclass of the class int, and cannot be subclassed.

### help
str(object='') -> str
str(bytes_or_buffer[, encoding[, errors]]) -> str

Create a new string object from the given object. If encoding or
errors is specified, then the object must expose a data buffer
that will be decoded using the given encoding and error handler.
Otherwise, returns the result of object.__str__() (if defined)
or repr(object).
encoding defaults to sys.getdefaultencoding().
errors defaults to 'strict'.

### hidden
bool(x) -> bool

Returns True when the argument x is true, False otherwise.
The builtins True and False are the only two instances of the class bool.
The class bool is a subclass of the class int, and cannot be subclassed.

### invoke_without_command
bool(x) -> bool

Returns True when the argument x is true, False otherwise.
The builtins True and False are the only two instances of the class bool.
The class bool is a subclass of the class int, and cannot be subclassed.

### name
str(object='') -> str
str(bytes_or_buffer[, encoding[, errors]]) -> str

Create a new string object from the given object. If encoding or
errors is specified, then the object must expose a data buffer
that will be decoded using the given encoding and error handler.
Otherwise, returns the result of object.__str__() (if defined)
or repr(object).
encoding defaults to sys.getdefaultencoding().
errors defaults to 'strict'.

### no_args_is_help
bool(x) -> bool

Returns True when the argument x is true, False otherwise.
The builtins True and False are the only two instances of the class bool.
The class bool is a subclass of the class int, and cannot be subclassed.

### options_metavar
str(object='') -> str
str(bytes_or_buffer[, encoding[, errors]]) -> str

Create a new string object from the given object. If encoding or
errors is specified, then the object must expose a data buffer
that will be decoded using the given encoding and error handler.
Otherwise, returns the result of object.__str__() (if defined)
or repr(object).
encoding defaults to sys.getdefaultencoding().
errors defaults to 'strict'.

### params
list() -> new empty list
list(iterable) -> new list initialized from iterable's items

### subcommand_metavar
str(object='') -> str
str(bytes_or_buffer[, encoding[, errors]]) -> str

Create a new string object from the given object. If encoding or
errors is specified, then the object must expose a data buffer
that will be decoded using the given encoding and error handler.
Otherwise, returns the result of object.__str__() (if defined)
or repr(object).
encoding defaults to sys.getdefaultencoding().
errors defaults to 'strict'.

### [cli](https://github.com/wandb/client/blob/feature/docs//Users/lukas/.pyenv/versions/wandb-3.6/lib/python3.6/site-packages/click/decorators.py#L224)
```python
cli(ctx)
```
Weights & Biases.

Run "wandb docs" for full documentation.


## [CallbackHandler](https://github.com/wandb/client/blob/feature/docs/wandb/cli.py#L74)
```python
CallbackHandler(self, request, client_address, server)
```
Simple callback handler that stores query string parameters and
shuts down the server.


## [LocalServer](https://github.com/wandb/client/blob/feature/docs/wandb/cli.py#L91)
```python
LocalServer(self)
```
A local HTTP server that finds an open port and listens for a callback.
The urlencoded callback url is accessed via `.qs` the query parameters passed
to the callback are accessed via `.result`


## [display_error](https://github.com/wandb/client/blob/feature/docs/wandb/cli.py#L146)
```python
display_error(func)
```
Function decorator for catching common errors and re-raising as wandb.Error

## [prompt_for_project](https://github.com/wandb/client/blob/feature/docs/wandb/cli.py#L163)
```python
prompt_for_project(ctx, entity)
```
Ask the user for a project, creating one if necessary.
