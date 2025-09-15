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
  - [ ] download python
  - [ ] download go (not really used ...)
- [ ] upload
  - [ ] upload python
  - [ ] upload go

RunFiles

- [ ] log run, upload and TBH I haven't changed that part of code (yet.)

## Artifact

### Artifact Download in Python

For artifact

- Upload is no longer using python, but the python code is still there...
- Download is in `wandb_storage_policy.py`
