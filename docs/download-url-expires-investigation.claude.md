# Download URL Expiration Investigation Summary

## Overview

This document summarizes the investigation into presigned URL expiration and multipart download issues in the wandb Python SDK artifact download path.

**Investigation is split into two parts for separate PRs:**
- **Part A**: Handling expired URL in multipart download
- **Part B**: Timeout/hanging issues in multipart download

---

## 1. Download Architecture

### Flow Diagram

```
Artifact.download()
  └── Artifact._download() [artifact.py:2039-2146]
      ├── _fetch_file_urls() - GraphQL query for presigned URLs (batched, with retry)
      ├── entry._download_url = node.direct_url (stores URL on entry)
      └── ThreadPoolExecutor(max_workers=64)
          └── _download_entry() for each file
              └── ArtifactManifestEntry.download()
                  └── WandbStoragePolicy.load_file() [wandb_storage_policy.py:115-176]
                      ├── Path A: multipart_download() for files ≥2GB
                      └── Path B: Serial session.get() for smaller files
```

### Key Files

| File | Path | Purpose |
|------|------|---------|
| artifact.py | `wandb/sdk/artifacts/artifact.py` | Artifact download orchestration, URL fetching |
| wandb_storage_policy.py | `wandb/sdk/artifacts/storage_policies/wandb_storage_policy.py` | File download logic, URL fallback |
| _multipart.py | `wandb/sdk/artifacts/storage_policies/_multipart.py` | Parallel chunk download implementation |
| _factories.py | `wandb/sdk/artifacts/storage_policies/_factories.py` | HTTP session and retry configuration |

---

## 2. URL Expiration Handling Analysis

### Current Mechanism

URLs are fetched via GraphQL queries (`GetArtifactFileUrls` or `GetArtifactMembershipFileUrls`) which return `directUrl` - a presigned URL with expiration.

**URL Fetching Code** (`artifact.py:2148-2209`):
```python
@retry.retriable(
    retry_timedelta=timedelta(minutes=3),
    retryable_exceptions=(requests.RequestException),
)
def _impl(cursor: str | None, per_page: int = 5000) -> FileWithUrlConnection:
    # Executes GraphQL query for file URLs with pagination
```

**URL Storage** (`artifact.py:2105`):
```python
entry._download_url = node.direct_url  # Set once, never refreshed
```

### Serial Download Path (HAS Fallback)

Location: `wandb_storage_policy.py:148-171`

```python
# Serial download
try:
    response = self._session.get(url, stream=True)
except requests.HTTPError:
    # Signed URL might have expired, fall back to fetching it one by one.
    manifest_entry._download_url = None

if manifest_entry._download_url is None:
    # Fallback: Use authenticated URL via Bearer token or API key
    auth = None
    headers: dict[str, str] = {}
    if token := self._api.access_token:
        headers = {"Authorization": f"Bearer {token}"}
    else:
        auth = ("api", self._api.api_key or "")

    file_url = self._file_url(artifact, manifest_entry)  # Builds authenticated URL
    response = self._session.get(file_url, auth=auth, headers=headers, stream=True)
```

### Multipart Download Path (NO Fallback) - CRITICAL GAP

Location: `wandb_storage_policy.py:142-146`

```python
if url := manifest_entry._download_url:
    # Use multipart parallel download for large file
    if executor and (size := manifest_entry.size):
        multipart_download(executor, self._session, url, size, cache_open)
        return path  # <-- Returns immediately, NO error handling or fallback!
```

**Problem**: If presigned URL expires during multipart download, the function raises an exception with no recovery mechanism.

---

## 3. Supporting Multiple URL Refreshes

### Current Limitation

URLs are fetched ONCE at the start of `_download()` before any downloads begin. There's no mechanism to:
1. Refresh a URL when it expires
2. Track URL expiration time
3. Proactively refresh URLs before expiration

### URL Sharing with Range Headers

The note in the requirements is correct: **One URL CAN be shared by multiple threads using different HTTP Range headers**. This is the standard approach for parallel downloads:

```python
# Each thread requests a different byte range from the same URL
headers = {"Range": f"bytes={start}-{end}"}  # e.g., "bytes=0-104857599"
session.get(url=url, headers=headers, stream=True)
```

### Recommendation: URL Refresh Callback

To support URL refresh during long downloads:

1. Add a callback parameter to `multipart_download`:
```python
def multipart_download(
    executor: Executor,
    session: Session,
    url: str,
    size: int,
    cached_open: Opener,
    part_size: int = MULTI_DEFAULT_PART_SIZE,
    get_fresh_url: Callable[[], str] | None = None,  # NEW: URL refresh callback
):
```

2. On 403/401 error in `download_chunk`, call `get_fresh_url()` and retry
3. The callback would re-execute the GraphQL query for that specific file

---

## 4. Multipart Download Concurrency Issues

### Architecture

```
Main Thread:
  ├── Creates MultipartDownloadContext with Queue(maxsize=500)
  ├── Submits write_chunks() to executor
  └── Submits download_chunk() for each part (100MB default)

download_chunk threads (multiple):
  └── session.get() with Range header
      └── iter_content() → q.put(ChunkContent)

write_chunks thread (single):
  └── Loop: q.get() → seek() → write()
```

### Issue A: No HTTP Timeout (HIGH RISK)

**Location**: `_multipart.py:132`

```python
with session.get(url=url, headers=headers, stream=True) as rsp:
    # NO timeout parameter - can block forever
```

**Impact**: If server hangs or network becomes unresponsive, this blocks indefinitely. Multiple download threads could hang, preventing the download from completing or failing cleanly.

**Recommendation**: Add timeout parameter:
```python
with session.get(url=url, headers=headers, stream=True, timeout=(10, 300)) as rsp:
    # (connect_timeout=10s, read_timeout=300s)
```

### Issue B: iter_content Can Hang (HIGH RISK)

**Location**: `_multipart.py:134-138`

```python
for chunk in rsp.iter_content(chunk_size=RSP_CHUNK_SIZE):
    if ctx.cancel.is_set():
        return
    ctx.q.put(ChunkContent(offset=offset, data=chunk))
```

**Impact**: If server stops sending data but doesn't close connection, `iter_content()` blocks waiting for more data. The cancel check only runs between chunks.

**Recommendation**: Configure socket-level timeout on the session or use a streaming timeout wrapper.

### Issue C: Queue Blocking (MEDIUM RISK)

**Location**: `_multipart.py:117`

```python
ctx = MultipartDownloadContext(q=Queue(maxsize=500))  # ~500MB buffer
```

**Scenario**: If disk I/O is slow (writer thread bottleneck), `q.put()` blocks when queue is full. This causes download threads to stall.

**Mitigation already exists**: The 500-item limit prevents unbounded memory growth, but can cause slowdowns.

### Issue D: Writer Thread Hang (MEDIUM RISK)

**Location**: `_multipart.py:140-156`

```python
def write_chunks() -> None:
    while not (ctx.cancel.is_set() or is_end_chunk(chunk := ctx.q.get())):
        # Blocks on q.get() if queue is empty
```

**Scenario**: If all download threads hang (e.g., no timeout), they never put `END_CHUNK` in queue. Writer thread blocks forever on `q.get()`.

**Existing mitigation** (`_multipart.py:188-191`):
```python
finally:
    ctx.q.put(END_CHUNK)
    write_future.result()
```

The `finally` block should signal the writer, BUT only if the main thread (waiting on `wait()`) isn't blocked.

### Issue E: Error Propagation (MEDIUM RISK)

**Location**: `_multipart.py:171-187`

```python
done, not_done = wait(download_futures, return_when=FIRST_EXCEPTION)
try:
    for fut in done:
        fut.result()  # Raises if exception
except Exception as e:
    ctx.cancel.set()
    for fut in not_done:
        fut.cancel()  # Note: doesn't stop running futures
    raise
```

**Issue**: `Future.cancel()` only prevents futures from starting, doesn't stop running ones. Relies on cooperative cancellation via `ctx.cancel.is_set()` check, which only happens between chunks.

---

## 5. Session Retry Configuration

**Location**: `_factories.py:27-60`

```python
HTTP_RETRY_STRATEGY = Retry(
    backoff_factor=1,
    total=16,  # ~20 minutes total retry time
    status_forcelist=(308, 408, 409, 429, 500, 502, 503, 504),
)
```

**Key observation**: **403 is NOT in status_forcelist**. The session will NOT retry on 403 errors (expired presigned URL). It raises `HTTPError` immediately.

The session also has a response hook:
```python
session.hooks["response"].append(raise_for_status)  # Raises HTTPError on 4xx/5xx
```

**Conclusion**: The "hanging" reported by users is NOT caused by retry loops on 403. It's likely from:
1. Missing HTTP timeouts
2. Download threads blocking on network I/O
3. Potential deadlock between download/writer threads

---

## 6. HTTP Timeout Configuration Analysis

### Python SDK Timeout Settings

| Component | Default Timeout | Environment Variable | Setting |
|-----------|-----------------|---------------------|---------|
| GraphQL API (InternalApi) | **20 seconds** | `WANDB_HTTP_TIMEOUT` | `x_graphql_timeout_seconds` |
| GraphQL API (Public API) | **19 seconds** | `WANDB_HTTP_TIMEOUT` | - |
| File Transfer (uploads) | **None** | `WANDB_FILE_PUSHER_TIMEOUT` | `x_file_transfer_timeout_seconds` |
| File Stream | **0 (no timeout)** | - | `x_file_stream_timeout_seconds` |
| Artifact file URL queries | **60 seconds** | Hardcoded | - |
| Init operation | **90 seconds** | - | `init_timeout` |

**Key Files:**
- `wandb/env.py:50-51` - Environment variable definitions (`HTTP_TIMEOUT`, `FILE_PUSHER_TIMEOUT`)
- `wandb/sdk/wandb_settings.py:560-590` - Settings definitions
- `wandb/sdk/internal/internal_api.py:216-217` - `HTTP_TIMEOUT = env.get_http_timeout(20)`, `FILE_PUSHER_TIMEOUT = env.get_file_pusher_timeout()`
- `wandb/sdk/lib/gql_request.py:25-77` - GraphQL session timeout handling

### Go Core Timeout Settings

| Component | Default Timeout | Proto Setting |
|-----------|-----------------|---------------|
| GraphQL API | **30 seconds** | `x_graphql_timeout_seconds` |
| FileStream | **180 seconds (3 min)** | `x_file_stream_timeout_seconds` |
| File Transfer | **0 (infinite)** | `x_file_transfer_timeout_seconds` |
| OpenMetrics/Monitoring | **5 seconds** | Hardcoded |

**Key Files:**
- `core/internal/api/api.go:32` - `DefaultNonRetryTimeout = 30 * time.Second`
- `core/internal/filestream/filestream.go:46` - `DefaultNonRetryTimeout = 180 * time.Second`
- `core/internal/filetransfer/file_transfer_retry_policy.go:16` - `DefaultNonRetryTimeout = 0 * time.Second`
- `core/internal/settings/settings.go:212-269` - Getter methods for timeout settings
- `wandb/proto/wandb_settings.proto:154,169,178` - Proto definitions for configurable timeouts

### Artifact Download - NO TIMEOUT CONFIGURED (CRITICAL)

The artifact download paths have **NO timeout** on HTTP requests:

```python
# wandb_storage_policy.py:150 - Serial download (NO timeout)
response = self._session.get(url, stream=True)

# _multipart.py:132 - Multipart download (NO timeout)
with session.get(url=url, headers=headers, stream=True) as rsp:
```

The session created in `_factories.py` has retry configuration but **no default timeout** set on the session itself or individual requests.

---

## Part A: Handling Expired URL in Multipart Download

### Problem Statement
- Multipart download path has no fallback when presigned URL expires
- Serial download has fallback to authenticated URL, but multipart doesn't
- For long downloads (e.g., 470GB model), URLs will almost certainly expire

### Root Cause
Location: `wandb_storage_policy.py:142-146`
```python
if url := manifest_entry._download_url:
    if executor and (size := manifest_entry.size):
        multipart_download(executor, self._session, url, size, cache_open)
        return path  # NO error handling!
```

### Recommended Fix for Part A
1. Wrap `multipart_download` in try/except for HTTPError (401, 403)
2. On error, fetch fresh URL and retry the entire download
3. For mid-download refresh: Add URL refresh callback parameter to `multipart_download`

### Files to Modify (Part A)
- `wandb/sdk/artifacts/storage_policies/wandb_storage_policy.py` - Add try/except around multipart_download
- `wandb/sdk/artifacts/storage_policies/_multipart.py` - Add URL refresh callback parameter

---

## Part B: Timeout/Hanging Issues in Multipart Download

### Problem Statement
- No HTTP timeout on download requests - can block forever
- `session.get()` blocks indefinitely if server hangs
- `iter_content()` hangs if server stops sending but doesn't close connection
- Writer thread can block forever waiting on queue

### Root Cause
Location: `_multipart.py:132`
```python
with session.get(url=url, headers=headers, stream=True) as rsp:
    # NO timeout parameter
```

### Recommended Fix for Part B
1. Add `timeout=(connect_timeout, read_timeout)` to `session.get()` calls
2. Consider using `x_file_transfer_timeout_seconds` setting for consistency with Go core
3. Add timeout to queue operations to prevent indefinite blocking
4. Optionally configure socket-level timeout on the session

### Files to Modify (Part B)
- `wandb/sdk/artifacts/storage_policies/_multipart.py` - Add timeout to `session.get()`
- `wandb/sdk/artifacts/storage_policies/_factories.py` - Consider adding default timeout to session
- `wandb/sdk/artifacts/storage_policies/wandb_storage_policy.py` - Add timeout to serial download path

---

## 7. Shared URL Approach for Multipart Downloads (Detailed Design)

### The Thundering Herd Problem

When a presigned URL expires during a multipart download, multiple chunk download threads may encounter 401/403 errors simultaneously. Without coordination, each thread would independently try to refresh the URL by calling the GraphQL API:

```
Thread 1: GET chunk 0-100MB → 403 → refresh URL → API call
Thread 2: GET chunk 100-200MB → 403 → refresh URL → API call
Thread 3: GET chunk 200-300MB → 403 → refresh URL → API call
... (N threads, N API calls for the same URL)
```

This wastes resources and can overwhelm the API with redundant requests.

### Solution: Shared URL Holder with TTL

Use a thread-safe URL holder that:
1. Caches the URL with a timestamp
2. Returns cached URL if recently fetched (within TTL)
3. Allows concurrent fetches but only updates if newer

```python
# New file: wandb/sdk/artifacts/storage_policies/_url_provider.py

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

class SharedUrlProvider:
    """Thread-safe URL provider with TTL-based caching.

    When multiple threads need to refresh an expired URL, this class ensures
    that recently-fetched URLs are reused rather than making redundant API calls.

    Design choices:
    - TTL (time-to-live): How long a fetched URL is considered "fresh enough" to reuse.
      Default 5 seconds - if a URL was fetched within the last 5 seconds, reuse it.
    - No strict single-flight: Multiple threads MAY fetch concurrently during the
      refresh window, but only the most recent result is kept. This is simpler than
      full single-flight coordination and sufficient for our use case.
    - Thread-safe via lock: All state mutations are protected by a lock.
    """

    def __init__(self, fetch_fn: Callable[[], str], ttl_seconds: float = 5.0):
        """Initialize the provider.

        Args:
            fetch_fn: Callable that fetches a fresh URL (e.g., GraphQL API call).
                     This function should be idempotent and thread-safe.
            ttl_seconds: How long a fetched URL is considered fresh. Threads that
                        need a URL within this window will reuse the cached one.
        """
        self._fetch_fn = fetch_fn
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._url: Optional[str] = None
        self._fetched_at: float = 0  # monotonic timestamp

    def get_url(self) -> str:
        """Get the current URL, fetching a fresh one if needed.

        Returns:
            The URL to use for download. May be cached if recently fetched.
        """
        now = time.monotonic()

        # Fast path: check if cached URL is still fresh
        with self._lock:
            if self._url and (now - self._fetched_at) < self._ttl:
                return self._url

        # Slow path: fetch a fresh URL
        # Note: Multiple threads may reach here simultaneously during the refresh
        # window. This is acceptable - we just use whichever fetch completes last.
        url = self._fetch_fn()
        fetch_time = time.monotonic()

        with self._lock:
            # Only update if our fetch is more recent than what's cached
            if fetch_time > self._fetched_at:
                self._url = url
                self._fetched_at = fetch_time
            return self._url or url

    def invalidate(self) -> None:
        """Mark the cached URL as invalid, forcing next get_url() to fetch fresh.

        Call this when a download fails with 401/403, indicating URL expiration.
        """
        with self._lock:
            self._fetched_at = 0  # Force refresh on next get_url()

    def set_initial_url(self, url: str) -> None:
        """Set the initial URL (e.g., from batch-fetched URLs).

        Args:
            url: The presigned URL fetched during artifact download initialization.
        """
        with self._lock:
            if not self._url:  # Only set if not already set
                self._url = url
                self._fetched_at = time.monotonic()
```

### Integration with Multipart Download

#### Option A: URL Provider in MultipartDownloadContext

Extend the existing context to include the URL provider:

```python
# In _multipart.py

@dataclass
class MultipartDownloadContext:
    q: Queue[QueuedChunk]
    cancel: threading.Event = field(default_factory=threading.Event)
    url_provider: Optional[SharedUrlProvider] = None  # NEW


def multipart_download(
    executor: Executor,
    session: Session,
    url: str,
    size: int,
    cached_open: Opener,
    part_size: int = MULTI_DEFAULT_PART_SIZE,
    url_provider: Optional[SharedUrlProvider] = None,  # NEW parameter
):
    """Download file as multiple parts in parallel.

    Args:
        url_provider: Optional SharedUrlProvider for refreshing expired URLs.
                     If provided, chunks will retry with fresh URLs on 401/403.
                     If None, 401/403 errors are raised immediately (legacy behavior).
    """
    ctx = MultipartDownloadContext(
        q=Queue(maxsize=500),
        url_provider=url_provider,
    )

    # Set initial URL in provider
    if url_provider:
        url_provider.set_initial_url(url)

    with cached_open("wb") as f:
        def download_chunk(start: int, end: int | None = None) -> None:
            if ctx.cancel.is_set():
                return

            # Get URL from provider (may be refreshed if expired)
            current_url = ctx.url_provider.get_url() if ctx.url_provider else url

            bytes_range = f"{start}-" if (end is None) else f"{start}-{end}"
            headers = {"Range": f"bytes={bytes_range}"}

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    with session.get(url=current_url, headers=headers, stream=True) as rsp:
                        # Check for auth errors before streaming
                        if rsp.status_code in (401, 403):
                            raise requests.HTTPError(response=rsp)

                        offset = start
                        for chunk in rsp.iter_content(chunk_size=RSP_CHUNK_SIZE):
                            if ctx.cancel.is_set():
                                return
                            ctx.q.put(ChunkContent(offset=offset, data=chunk))
                            offset += len(chunk)
                        return  # Success, exit retry loop

                except requests.HTTPError as e:
                    if e.response is not None and e.response.status_code in (401, 403):
                        if ctx.url_provider and attempt < max_retries - 1:
                            # Invalidate and get fresh URL
                            ctx.url_provider.invalidate()
                            current_url = ctx.url_provider.get_url()
                            continue  # Retry with new URL
                    raise  # Re-raise if not retryable or max retries exceeded

        # ... rest of the function unchanged
```

#### Option B: Simpler Wrapper Approach

If you prefer minimal changes to `_multipart.py`, wrap the entire multipart download with retry logic in `load_file`:

```python
# In wandb_storage_policy.py

def load_file(
    self,
    artifact: Artifact,
    manifest_entry: ArtifactManifestEntry,
    dest_path: str | None = None,
    executor: concurrent.futures.Executor | None = None,
) -> FilePathStr:
    # ... cache check code ...

    if url := manifest_entry._download_url:
        if executor and (size := manifest_entry.size):
            # Create URL provider with refresh callback
            def fetch_fresh_url() -> str:
                return self._fetch_single_file_url(artifact, manifest_entry)

            url_provider = SharedUrlProvider(fetch_fn=fetch_fresh_url, ttl_seconds=5.0)
            url_provider.set_initial_url(url)

            multipart_download(
                executor,
                self._session,
                url,
                size,
                cache_open,
                url_provider=url_provider,
            )
            return path

        # Serial download path (unchanged)
        # ...
```

### Fetching Single File URL via GraphQL

The existing GraphQL infrastructure already supports fetching a single file's URL via the `fileNames` filter parameter. This is the recommended approach instead of the HTTP fallback in `wandb_storage_policy.py:155-172`.

**Available Queries (already exist):**
- `GET_ARTIFACT_FILES_GQL` - with `fileNames: [String!]` parameter (operations.py:376)
- `GET_ARTIFACT_MEMBERSHIP_FILES_GQL` - with `fileNames: [String!]` parameter (operations.py:418)

Both return `FileFragment` which includes `direct_url` (the presigned URL).

**Implementation - Add to `artifact.py` (Artifact class):**

```python
def _fetch_single_file_url(self, file_name: str) -> str | None:
    """Fetch a fresh presigned URL for a single file.

    This is used when a URL expires during download and needs to be refreshed.
    Reuses the existing GraphQL infrastructure with fileNames filter.

    Args:
        file_name: The file name/path within the artifact manifest.

    Returns:
        The presigned URL for the file, or None if not found.
    """
    from gql import gql

    from wandb.sdk.artifacts._generated import (
        GET_ARTIFACT_FILES_GQL,
        GET_ARTIFACT_MEMBERSHIP_FILES_GQL,
        GetArtifactFiles,
        GetArtifactMembershipFiles,
    )

    if self._client is None:
        raise RuntimeError("Client not initialized")

    # Use the membership query if server supports it (same logic as batch fetch)
    if server_supports(self._client, pb.ARTIFACT_COLLECTION_MEMBERSHIP_FILES):
        query = gql(GET_ARTIFACT_MEMBERSHIP_FILES_GQL)
        gql_vars = {
            "entity": self.entity,
            "project": self.project,
            "collection": self.name.split(":")[0],
            "alias": self.version,
            "fileNames": [file_name],  # Filter to single file
            "perPage": 1,
        }
        data = self._client.execute(query, variable_values=gql_vars, timeout=60)
        result = GetArtifactMembershipFiles.model_validate(data)

        if not (
            (project := result.project)
            and (collection := project.artifact_collection)
            and (membership := collection.artifact_membership)
            and (files := membership.files)
            and files.edges
            and (node := files.edges[0].node)
        ):
            return None
        return node.direct_url
    else:
        # Fallback to artifact-based query
        query = gql(GET_ARTIFACT_FILES_GQL)
        gql_vars = {
            "entity": self.entity,
            "project": self.project,
            "type": self.type,  # artifact type name
            "name": self.name,
            "fileNames": [file_name],
            "perPage": 1,
        }
        data = self._client.execute(query, variable_values=gql_vars, timeout=60)
        result = GetArtifactFiles.model_validate(data)

        if not (
            (project := result.project)
            and (artifact_type := project.artifact_type)
            and (artifact := artifact_type.artifact)
            and (files := artifact.files)
            and files.edges
            and (node := files.edges[0].node)
        ):
            return None
        return node.direct_url
```

**Updated SharedUrlProvider factory in `wandb_storage_policy.py`:**

```python
# In WandbStoragePolicy.load_file()

if url := manifest_entry._download_url:
    if executor and (size := manifest_entry.size):
        # Create URL provider with GraphQL-based refresh callback
        def fetch_fresh_url() -> str:
            fresh_url = artifact._fetch_single_file_url(str(manifest_entry.path))
            if fresh_url is None:
                raise ValueError(
                    f"Failed to fetch URL for file: {manifest_entry.path}"
                )
            return fresh_url

        url_provider = SharedUrlProvider(fetch_fn=fetch_fresh_url, ttl_seconds=5.0)
        url_provider.set_initial_url(url)

        multipart_download(
            executor,
            self._session,
            url,
            size,
            cache_open,
            url_provider=url_provider,
        )
        return path
```

**Why GraphQL over HTTP fallback (`_file_url` approach):**

| Aspect | GraphQL Approach | HTTP Fallback (`_file_url`) |
|--------|------------------|----------------------------|
| **Consistency** | Uses same client/queries as batch fetch | Bypasses GraphQL, direct HTTP |
| **URL Type** | Returns presigned URL (same as batch) | Returns authenticated endpoint URL |
| **Server Changes** | Explicit failure if query changes | May silently break on SDK changes |
| **Type Safety** | Generated Pydantic models | Manual URL construction |
| **Retry Logic** | Can leverage GraphQL retry | Separate retry handling needed |
| **Token Handling** | Managed by GraphQL client | Manual Bearer/API key handling |

The GraphQL approach is preferred because it reuses the exact same code path that generates the original presigned URLs, ensuring consistency.

### Flow Diagram with SharedUrlProvider

```
Artifact.download()
  └── ThreadPoolExecutor(max_workers=64)
      └── _download_entry() for each file
          └── WandbStoragePolicy.load_file()
              ├── Creates SharedUrlProvider(fetch_fn=_fetch_single_file_url)
              └── multipart_download(url_provider=provider)
                  └── download_chunk() threads (each part)
                      ├── url = url_provider.get_url()  ← Returns cached or fresh
                      ├── session.get(url, Range=...)
                      ├── On 401/403:
                      │   ├── url_provider.invalidate()
                      │   └── url = url_provider.get_url()  ← Fetches fresh, others reuse
                      └── Retry with fresh URL
```

### Thread Safety Analysis

```
Time →
Thread 1: get_url() → cached URL → GET → 403 → invalidate() → get_url() → [FETCH] → new URL
Thread 2: get_url() → cached URL → GET → 403 → invalidate() → get_url() → [WAIT/FETCH] → new URL
Thread 3: get_url() → cached URL → GET → 403 → invalidate() → get_url() → [WAIT/REUSE] → new URL
                                                                              ↑
                                                                    TTL window: reuses Thread 1's fetch
```

- **invalidate()**: Multiple threads can call this; it just resets the timestamp
- **get_url()**: Thread-safe; worst case is 2-3 concurrent fetches during refresh window
- **TTL (5 seconds)**: After any thread fetches, others within 5 seconds reuse it

### Configuration Considerations

```python
# Possible environment variable for TTL
URL_REFRESH_TTL = env.get("WANDB_URL_REFRESH_TTL", 5.0)

# Or as a setting in wandb_settings.py
x_artifact_url_refresh_ttl: float = Field(
    default=5.0,
    description="TTL in seconds for caching refreshed artifact download URLs",
)
```

### Edge Cases

1. **All threads hit 403 simultaneously**: First thread to complete `get_url()` refresh wins; others reuse within TTL
2. **URL expires during chunk download**: Current chunk fails, retry gets fresh URL from provider
3. **Refresh API call fails**: Exception propagates up, download fails (existing behavior)
4. **Very slow network**: TTL may expire while threads are still downloading; next 403 triggers another refresh (acceptable)

---

## 8. Recommendations for Fix (Combined)

### Priority 1: Add HTTP Timeout to Multipart Download

```python
# In download_chunk function
with session.get(url=url, headers=headers, stream=True, timeout=(10, 300)) as rsp:
```

### Priority 2: Add SharedUrlProvider for URL Refresh

1. Create `_url_provider.py` with `SharedUrlProvider` class
2. Integrate with `multipart_download()` as optional parameter
3. Use 5-second TTL to coalesce refresh requests

### Priority 3: Handle URL Expiration in download_chunk

Add retry loop in `download_chunk()`:
```python
for attempt in range(max_retries):
    try:
        current_url = url_provider.get_url() if url_provider else url
        with session.get(url=current_url, headers=headers, stream=True) as rsp:
            # ... download logic
    except requests.HTTPError as e:
        if e.response.status_code in (401, 403) and url_provider:
            url_provider.invalidate()
            continue
        raise
```

### Priority 4: Improve Cancellation Handling

Add timeout to queue operations:
```python
try:
    ctx.q.put(ChunkContent(...), timeout=60)  # 60s timeout
except queue.Full:
    if ctx.cancel.is_set():
        return
    raise
```

---

## 9. Test Files for Reference

| File | Purpose |
|------|---------|
| `tests/unit_tests/test_artifacts/test_wandb_artifacts.py` | Unit tests including `test_artifact_multipart_download_network_error`, `test_artifact_multipart_download_disk_error` |
| `tests/system_tests/test_artifacts/test_wandb_artifacts_api.py` | System test `test_artifact_multipart_download` |

---

## 10. Code Locations Quick Reference

| Issue | File | Lines |
|-------|------|-------|
| Multipart download entry | wandb_storage_policy.py | 142-146 |
| Serial download fallback | wandb_storage_policy.py | 148-171 |
| URL fetching | artifact.py | 2148-2209 |
| URL storage | artifact.py | 2105 |
| multipart_download function | _multipart.py | 102-192 |
| download_chunk (no timeout) | _multipart.py | 122-138 |
| Queue creation | _multipart.py | 117 |
| Session retry config | _factories.py | 37-41 |
