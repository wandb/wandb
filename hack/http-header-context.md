# HTTP Header Context

Use Python context manager to set headers and pass them to Go core.

## TODO

- [ ] finalize where to set the headers
  - [ ] wandb cli might still need to use parameter/envrionment variable
  - [ ] there is existing thread local settings for headers, using contextvars seems be more pythonic...
  - [ ] `x_extra_http_headers` in settings is for graphql and file stream, we are reusing it for object storage, but do we want to split them?
- [x] artifact upload and download
- [x] proxy servers, see [cmd/wapiproxy/](cmd/wapiproxy/) and [cmd/ws3proxy/](cmd/ws3proxy/)

## Usage

Start the proxy servers and check the logs.
File proxy would print all requests missing the `X-My-Header-*` headers into `logs/file_proxy_missing_header.log`.

```bash
# Pick either GCS or S3
export WANDB_OBJECT_STORAGE_PREFIX=https://storage.googleapis.com/wandb-artifacts-prod
# export WANDB_OBJECT_STORAGE_PREFIX=https://pinglei-byob-us-west-2.s3.us-west-2.amazonaws.com
./start_proxy.sh

uv pip install -e ~/go/src/github.com/wandb/wandb
python3 test_headers.py
```

## Background

Instead of using environment variables like https://github.com/wandb/wandb/pull/10510/files,
we want to use a context manager to set headers so it looks like this:

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
We need to do something similar for downloading/uploading files.

The Go side needs to pass the headers via proto when starting a run/stream/calling API directly.

## Proto

TL;DR existing `x_extra_http_headers` in settings works. But we may want to introduce some new fields.

- [x] figure out how to regenerate the proto
- [x] where do we send the proto message?
  - For now, I just update `ServiceConnection.inform_init` to pass the headers when creating a new stream. It will inject them into the file transfer manager and apply them to all file transfers.
- [x] Actually, we might just set it in settings; otherwise, we need to modify the stream injection logic and pass a new parameter throughout.

### Generate proto

```bash
# Thanks Tony, without this, grpc builds cpp code from source and fails...
export GRPC_PYTHON_BUILD_SYSTEM_ZLIB=1
nox -s proto-python
nox -s proto-go
```

### RecordInfo

```proto

/*
 * _RecordInfo, _RequestInfo: extra info for all records and requests
 */
message _RecordInfo {
  string stream_id = 1;
  string _tracelog_id = 100;
  // FIXME: remove it, we already have x_extra_http_headers in Settings
  // map<string, string> headers = 101;
}
```

### x_extra_http_headers

There is actually an `x_extra_http_headers` in settings, not sure if it is ever used...

```proto
  // Additional headers to add to all outgoing HTTP requests.
  MapStringKeyStringValue x_extra_http_headers = 14;
```

It seems to be used for GraphQL and filestream

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

Updated file transfer logic to use the headers from settings.
It works, but the main issue is that headers are mixed for both W&B API and object storage.
We might consider splitting them in the proto. Though all these proto definitions
should be internal and do not impact the public API interface,
unless we allow users to configure the settings via a Python settings class.

## Python

There are 3 places we modified

- Artifact
  - `Artifact._load_manifest` for downloading `wandb_manfiest.json`
  - `WandbStoragePolicy` for downloading files (will migrate to go later)
- RunFiles
  - Upload is using go core, set the headers in `InformInit` via `x_extra_http_headers` in settings works
  - Download is using API (see below)
- API
  - `util.download_file_from_url` usings `/files` url, updated the methods to get headers from context.

Though wandb cli still have issue ... might still need to support environment variable, at least for cli.

### Context

We are using contextvars for passing the headers.
It is different from current used of `_thread_local_api_settings.headers`.

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

## Go

GO side is straightforawd, all the file operations are attached to a stream (run).
Pass the headers via settings `x_extra_http_headers` and apply them to file transfer manager into default file transfer.
Previously they were only applied to graphql and file stream clients.

Now both run file and artifact upload/download has the headers.

- [ ] Artifact download for downloading manifest is not using the headers...

## Proxy

Two proxy servers

- [cmd/wapiproxy/](cmd/wapiproxy/) hijack response from wandb api to replace s3 url with file proxy url
- [cmd/ws3proxy/](cmd/ws3proxy/) make actual call to s3 and print all the request headers, log requests missing custom headers

In API proxy, it replaces s3/gcs url to the `http://localhost:8182/` url.
In file proxy, it replace the url back to the original s3/gcs url.

For claude:

Update the proxy servers so they supports configuring the object storage url.
Right now it is hard coded to `https://pinglei-byob-us-west-2.s3.us-west-2.amazonaws.com` but I want to make it configurable in the file proxy server so `https://storage.googleapis.com/wandb-artifacts-prod` can also be used.
It can be set via environment variable `WANDB_OBJECT_STORAGE_PREFIX` in `start_proxy.sh`.
Servers should bail out if the environment variable is not set.
