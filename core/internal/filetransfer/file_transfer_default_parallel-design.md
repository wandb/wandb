# Parallel File Transfer Design

## Background

Currently the download logic is serial in go but parallel in python

Go code

- `file_transfer_default.go`. `func (ft *DefaultFileTransfer) Download(task *DefaultDownloadTask)`

Python code

- `wandb/sdk/artifacts/storage_policies/wandb_storage_policy.py`. `def _multipart_file_download(self, executor: concurrent.futures.Executor, download_url: str, file_size_bytes: int, cache_open: Opener):`

We want to do parallel download in go base on file size as well.
For go routine mangagement, we can use existing parallel hash logic from upload as example.
Parallel hash logic is in `core/pkg/artifacts/multipart.go`.

I want you to

- Read related code and come up with a design for parallel download in go in `file_transfer_default.go`.
- Write down your design and tasks in `file_transfer_default_parallel-impl.md`.
- Consider if we need to refactor on existing file related code, what can we reuse across download, upload especially for the parallel part.
