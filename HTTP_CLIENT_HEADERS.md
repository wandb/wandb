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

- [ ] manifest file
  - [x] `Artifact._load_manifest` in `artifact.py`
  - [ ] `core/pkg/artifacts/manifest.go` https://github.com/search?q=repo%3Awandb%2Fwandb+go-retryablehttp&type=code&p=1
- [ ] download
  - [x] download python
  - [x] download go, not enabled (yet)
- [ ] upload
  - [x] upload go
  - [ ] upload python, no longer used

RunFiles

- [ ] log run, upload and TBH I haven't changed that part of code (yet.)

## Artifact

### Artifact manifest download in Python

I think the upload of manifest file is in go ...
The download was using requests directly in `Artifact._load_manifest`

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

## Python

There is a `WANDB__EXTRA_HTTP_HEADERS` on `internal_api.py` which is also used in `upload_job.py`
But seems it is no longer used for anything ...

```python
class Api:
     def __init__(
        self,
        default_settings: Optional[
            Union[
                "wandb.sdk.wandb_settings.Settings",
                "wandb.sdk.internal.settings_static.SettingsStatic",
                Settings,
                dict,
            ]
        ] = None,
        load_settings: bool = True,
        retry_timedelta: datetime.timedelta = datetime.timedelta(  # okay because it's immutable
            days=7
        ),
        environ: MutableMapping = os.environ,
        retry_callback: Optional[Callable[[int, str], Any]] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self._environ = environ
        self._global_context = context.Context()
        self._local_data = _ThreadLocalData()
        self.default_settings: DefaultSettings = {
            "section": "default",
            "git_remote": "origin",
            "ignore_globs": [],
            "base_url": "https://api.wandb.ai",
            "root_dir": None,
            "api_key": None,
            "entity": None,
            "organization": None,
            "project": None,
            "_extra_http_headers": None,
            "_proxies": None,
        }
        self.retry_timedelta = retry_timedelta
        # todo: Old Settings do not follow the SupportsKeysAndGetItem Protocol
        default_settings = default_settings or {}
        self.default_settings.update(default_settings)  # type: ignore
        self.retry_uploads = 10
        self._settings = Settings(
            load_settings=load_settings,
            root_dir=self.default_settings.get("root_dir"),
        )
        self.git = GitRepo(remote=self.settings("git_remote"))
        # Mutable settings set by the _file_stream_api
        self.dynamic_settings = {
            "system_sample_seconds": 2,
            "system_samples": 15,
            "heartbeat_seconds": 30,
        }

        # todo: remove these hacky hacks after settings refactor is complete
        #  keeping this code here to limit scope and so that it is easy to remove later
        self._extra_http_headers = self.settings("_extra_http_headers") or json.loads(
            self._environ.get("WANDB__EXTRA_HTTP_HEADERS", "{}")
        )
        self._extra_http_headers.update(_thread_local_api_settings.headers or {})
```
