# HTTP Client Headers

Human version of [HTTP_CLIENT_FINDINGS.md](HTTP_CLIENT_FINDINGS.md).
The goal is to inject custom http headers when using presigned urls against object storage.
NOTE: these headers are not signed, they just got passed to the object storage.

## Design

Subject to change base on discussion with SDK team, for now:

- Single env var to set the headers using JSON.
- Use `WANDB_STORAGE_HTTP_HEADERS` to indicate it is only for storage operations (NOT for other API operations).

```bash
export WANDB_STORAGE_HTTP_HEADERS='{"X-MY-HEADER-A": "valueA", "X-MY-HEADER-B": "valueB"}'
```

## Implementation

We can start with python and then do go. Download is simple, we start on download file without a run.

Artifact

- [ ] download
  - [x] download python
  - [ ] download go, not enabled (yet)
- [ ] upload
  - [ ] upload go
  - [ ] upload python, no longer used

RunFiles

- [ ] log run, upload and TBH I haven't changed that part of code (yet.)

## Artifact

### Artifact Download in Python

For artifact

- Upload is no longer using python, but the python code is still there...
- Download is in `wandb_storage_policy.py`

Following code works

```python
HTTP_HEADERS_ENV_VAR = "WANDB_STORAGE_HTTP_HEADERS"


class EnvHeaderAdapter(HTTPAdapter):
    """Adapter that adds headers from the environment variable to all the request."""

    _headers: dict[str, str] = {}

    def __init__(self):
        super().__init__(
            max_retries=_REQUEST_RETRY_STRATEGY,
            pool_connections=_REQUEST_POOL_CONNECTIONS,
            pool_maxsize=_REQUEST_POOL_MAXSIZE,
        )
        # Parse the headers from the env var (if present)
        if os.environ.get(HTTP_HEADERS_ENV_VAR):
            self._headers = json.loads(os.environ.get(HTTP_HEADERS_ENV_VAR))

    def add_headers(self, request, **kwargs):
        # Skip calling super because it does nothing by default
        request.headers.update(self._headers)
```

### Artifact Upload in Go

The logic is in `filestransfer`

- Upload is already setting `headers` from `task.Headers`
- Download does not set anything
