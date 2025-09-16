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

- [x] figure out how to regenerate the proto
- [x] where do we send the proto message?
  - For now I just update `ServiceConnection.inform_init` to pass the headers when creating a new stream, it will inject into file transfer manager and goes to all the file transfers.
- [x] Actually might just set it in settings, otherwise we need to modify the stream injection logic and pass a new parameter all around.

```bash
# Thanks Tony, without this, grpc is building cpp code from source and failed...
export GRPC_PYTHON_BUILD_SYSTEM_ZLIB=1
nox -s proto-python
nox -s proto-go
```

There is actually a `x_extra_http_headers` in settings, not sure if it is every used ...

```proto
  // Additional headers to add to all outgoing HTTP requests.
  MapStringKeyStringValue x_extra_http_headers = 14;
```

Seems it is used for graphql, filestream

https://github.com/wandb/wandb/blob/be8c808bd8ce7d6db6a5e2c703ae82018a5cf5c0/core/internal/stream/stream_init.go#L107-L123

```go
// stream_init.go

// func NewGraphQLClient
graphqlHeaders := map[string]string{
    "X-WANDB-USERNAME":   settings.GetUserName(),
    "X-WANDB-USER-EMAIL": settings.GetEmail(),
}
maps.Copy(graphqlHeaders, settings.GetExtraHTTPHeaders())

// func NewFileStream
fileStreamHeaders := map[string]string{}
maps.Copy(fileStreamHeaders, settings.GetExtraHTTPHeaders())
if settings.IsSharedMode() {
    fileStreamHeaders["X-WANDB-USE-ASYNC-FILESTREAM"] = "true"
    fileStreamHeaders["X-WANDB-ASYNC-CLIENT-ID"] = string(clientID)
}
if settings.IsEnableServerSideDerivedSummary() {
    fileStreamHeaders["X-WANDB-SERVER-SIDE-DERIVED-SUMMARY"] = "true"
}

```

Using headers from `x_extra_http_headers` in settings works.
The main issue is it is mixed for both wandb api and object storage.
We might consider split them in the proto. Though all these proto
should be internal and does not impact the public API interface.
Unless we allow user to configure the settings via a python settings class.

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
