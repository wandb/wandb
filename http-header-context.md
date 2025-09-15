# HTTP Header Context

Use python context manager to set headers and pass to go core.

## Background

Instead of using environment variable like https://github.com/wandb/wandb/pull/10510/files
We want use context manager to set headers so it looks like this:

```python
# We can pass other things if we want to
with wandb.object_storage_context(headers={"foo": "bar"}):
    # run
    with wandb.init() as run:
        # get the headers from context
        run.log_artifact(....)
    # api
    api = wandb.Api()
    artifact = api.artifact("project/artifact:version")
    # get the headers from context
    artifact.download()
```

Related python PR https://github.com/wandb/wandb/pull/10417/files for graphql client.
We need to do similar thing for downloading/uploading file

Go side need to pass the headers via proto when starting a run/stream/calling API directly.

## Proto

- [ ] figure out how to regenerate the proto

```bash
# Thanks Tony, without this, grpc is building cpp code from source and failed...
export GRPC_PYTHON_BUILD_SYSTEM_ZLIB=1
nox -s proto-python
nox -s proto-go
```

## Python

Context

```python
from contextlib import contextmanager
import contextvars

_headers = contextvars.ContextVar("object_storage_headers", default={})

@contextmanager
def with_headers(headers: dict):
    old = _headers.set(headers)
    try:
        yield
    finally:
        _headers.reset(old)

def get_headers():
    return _headers.get()

def print_headers():
    print(get_headers())
    # actual logic of injecting headers

def main():
    with with_headers({"X-My-Header-A": "valueA", "X-My-Header-B": "valueB"}):
        print("Inside context")
        print_headers()

    print("Outside context")
    print_headers()

if __name__ == "__main__":
    main()
```
