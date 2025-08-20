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

## Things to address in the implementation doc

- We don't need to make head request to get the file size, the task struct already have file size.
- We can first put the logic in existing `file_transfer_default.go` to get things working first, then consider extract common logic out for reuse in other pacakges.
- We can skip the retry, the http client we are using already has retry logic.
- For the progress tracking, we might not need the lock because we have a single goroutine for writing the file. We can also skip the progress tracking in the first iteration.
