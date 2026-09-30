# Coding style guide

This file describes specific practices that are mentioned frequently in PR
reviews. See also [general_advice.md](./general_advice.md).

## Style for all languages

### Explain "why?" in comments

Non-obvious choices should be documented in comments. Avoid writing comments
that just repeat the code, but do write comments to explain why the code exists.

```python
# BAD:
# Turn off propagate
_logger.propagate = False

# GOOD:
# Do not propagate wandb logs to the root logger, which the user may have
# configured to point elsewhere. All wandb log messages should go to a run's
# log file.
_logger.propagate = False
```

### Reduce nesting with guard clauses and early returns

Return early on edge cases and keep the happy path at the lowest level of
indentation.

```python
# BAD:
def my_function(a: int) -> None
    if a > 0:
        ... # the "happy" path
        return

    raise ValueError


# GOOD:
def my_function(a: int) -> None
    if a <= 0:
        raise ValueError

    ... # the "happy" path
```

See [PR #11248](https://github.com/wandb/wandb/pull/11248) (9dc24d272676ba0825407791c316b279dcc0b168)
for an example of rewriting bad nesting.

### Decompose long or complex functions

When something is hard to follow, extract well-named and documented helpers.
Refactor complex functions before adding more behavior: the worst monstrosities
are grown over many PRs that patch on functionality.

Never ignore the complexity lint.

### Handle errors once

Either handle an error or return it / raise it, but not both.

This is a common best practice whose main purpose is to avoid double-logging an
error, which makes logs less useful. If you follow this rule, then if you catch
an error, you can expect that it hasn't already been logged. If you don't follow
the rule, it's easy to double-log by accident, like after refactoring a function
that didn't log an error to start logging.

Another reason to do this is that higher level code can add more context to
an error and make it more useful.

## Python style

### Keep your hands to yourself

A leading underscore in Python marks a symbol as private, meaning it should
not be accessed outside the file or class in which it is defined. Accessing
`obj._foo` from outside its module signals a missing public API, and you should
either add one or (more likely) restructure your code.

One exception is that underscored methods in an abstract base class may
be used or overridden in subclasses **if the docstring says so**.
This corresponds to the "protected" access specifier in C++ or Java.
Anything without a docstring must be assumed to be private.

### Do not underscore parameters and locals

Local variables and function parameters should never be underscored in Python
because that is meaningless.

Do not try to add "private" parameters to public functions to use them in
internal code. Fix the dependency instead: public functions should depend on
internal code, not the other way around.

## Go style

### References

There is a lot of good advice here: https://github.com/uber-go/guide/blob/master/style.md

### Enhance errors with `fmt.Errorf()`

Go doesn't have stack traces, so to add context to an error, you wrap it
using `fmt.Errorf()` like so:

```go
if err != nil {
	return fmt.Errorf("filestream: error constructing request: %v", err)
}
```

In this repository, we use `%v`, not `%w` to wrap an error. Use `%w` only
if callers are expected to use `errors.Is()` to check the error type, which
is rare, or if your function transparently wraps another function, which is even
more rare.

You may want to prefix the error message with `packagename:`, which produces
something similar to a stacktrace when an error bubbles up through many layers
of functions. Whether you do this depends on how the function is used. The only
rule is to think about whether the resulting errors will be readable and
concise.
