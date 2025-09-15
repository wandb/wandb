# HTTP Client Usage for Signed URL Operations in W&B SDK

## Overview
This document provides a comprehensive analysis of HTTP client usage for file upload/download operations via signed URLs in both the Go (core) and Python SDK implementations.

## Go Implementation (Core)

### Key Files and Components

#### 1. File Transfer Default Handler
**Location:** `core/internal/filetransfer/file_transfer_default.go`

```go
// Lines 44-94: Upload method
func (ft *DefaultFileTransfer) Upload(task *DefaultUploadTask) error {
    // Uses retryablehttp.Client for HTTP operations
    req, err := retryablehttp.NewRequest(http.MethodPut, task.Url, requestBody)
    
    // Headers are set from task.Headers
    for _, header := range task.Headers {
        parts := strings.SplitN(header, ":", 2)
        if len(parts) != 2 {
            ft.logger.Error("file transfer: upload: invalid header", "header", header)
            continue
        }
        req.Header.Set(parts[0], parts[1])
    }
    
    resp, err := ft.client.Do(req)
}

// Lines 97-151: Download method
func (ft *DefaultFileTransfer) Download(task *DefaultDownloadTask) error {
    // Uses retryablehttp.Client.Get for downloads
    resp, err := ft.client.Get(task.Url)
}
```

**Key Points:**
- Uses `github.com/hashicorp/go-retryablehttp` for HTTP client with built-in retry logic
- Headers are applied from `task.Headers` array for uploads
- Direct GET request for downloads (no custom headers currently applied)

#### 2. Artifact Downloader
**Location:** `core/pkg/artifacts/downloader.go:106-134`

```go
// Downloads files using signed URLs obtained from GraphQL API
entry.DownloadURL = &node.DirectUrl
```

### Current HTTP Client Configuration in Go

The Go implementation uses:
1. **retryablehttp.Client** - A resilient HTTP client with automatic retries
2. **Headers** - Currently set from task headers during upload
3. **No environment-based header injection** currently implemented

## Python Implementation (SDK)

### Key Files and Components

#### 1. Upload Job Handler
**Location:** `wandb/filesync/upload_job.py:91-140`

```go
// Lines 104-121: Gets signed URL and uploads
_, upload_headers, result = self._api.upload_urls(project, [self.save_name])
file_info = result[self.save_name]
upload_url = file_info["uploadUrl"]

// Lines 113-129: Sets headers and uploads
extra_headers = self._api._extra_http_headers
for upload_header in upload_headers:
    key, val = upload_header.split(":", 1)
    extra_headers[key] = val
    
self._api.upload_file_retry(
    upload_url,
    f,
    lambda _, t: self.progress(t),
    extra_headers=extra_headers,
)
```

#### 2. Internal API Implementation
**Location:** `wandb/sdk/internal/internal_api.py`

```python
# Lines 3009-3075: Upload file method
def upload_file(self, url, file, callback=None, extra_headers=None):
    extra_headers = extra_headers.copy() if extra_headers else {}
    
    # Line 3043-3045: Actual HTTP PUT request
    response = self._upload_file_session.put(
        url, data=progress, headers=extra_headers
    )
```

```python
# Lines 2867-2891: Download file method
def download_file(self, url):
    http_headers = _thread_local_api_settings.headers or {}
    
    # Line 2886-2891: Actual HTTP GET request
    response = requests.get(
        url,
        headers=http_headers,
        cookies=_thread_local_api_settings.cookies,
        auth=auth,
        stream=True,
    )
```

#### 3. HTTP Handler for Artifacts
**Location:** `wandb/sdk/artifacts/storage_handlers/http_handler.py:51-57`

```python
# Downloads with custom headers from thread-local settings
response = self._session.get(
    manifest_entry.ref,
    stream=True,
    cookies=_thread_local_api_settings.cookies,
    headers=_thread_local_api_settings.headers,
)
```

### Current HTTP Client Configuration in Python

The Python implementation uses:
1. **requests.Session** - Standard Python HTTP client
2. **Retry logic** - Wrapped with custom retry mechanism
3. **Headers** - Applied from multiple sources:
   - `_extra_http_headers` from API
   - Upload headers from server response
   - Thread-local settings for some operations

## Recommendations for Environment Variable-Based Headers

### Go Implementation

#### Approach 1: Modify DefaultFileTransfer (Recommended)
```go
// In file_transfer_default.go
import "os"

func (ft *DefaultFileTransfer) Upload(task *DefaultUploadTask) error {
    // ... existing code ...
    
    // Add environment-based headers
    if envHeaders := os.Getenv("WANDB_HTTP_HEADERS"); envHeaders != "" {
        // Parse JSON or comma-separated headers
        // Example format: "Header1:Value1,Header2:Value2"
        for _, header := range strings.Split(envHeaders, ",") {
            parts := strings.SplitN(header, ":", 2)
            if len(parts) == 2 {
                req.Header.Set(strings.TrimSpace(parts[0]), strings.TrimSpace(parts[1]))
            }
        }
    }
    
    // ... rest of the method
}

// Similar modification for Download method
func (ft *DefaultFileTransfer) Download(task *DefaultDownloadTask) error {
    // Create custom request with headers
    req, err := retryablehttp.NewRequest(http.MethodGet, task.Url, nil)
    
    // Add environment-based headers
    if envHeaders := os.Getenv("WANDB_HTTP_HEADERS"); envHeaders != "" {
        for _, header := range strings.Split(envHeaders, ",") {
            parts := strings.SplitN(header, ":", 2)
            if len(parts) == 2 {
                req.Header.Set(strings.TrimSpace(parts[0]), strings.TrimSpace(parts[1]))
            }
        }
    }
    
    resp, err := ft.client.Do(req)
    // ... rest of the method
}
```

#### Approach 2: Configure retryablehttp.Client
```go
// When creating the client
func NewDefaultFileTransfer(...) *DefaultFileTransfer {
    client := retryablehttp.NewClient()
    
    // Wrap the client's HTTP client to add headers
    originalTransport := client.HTTPClient.Transport
    client.HTTPClient.Transport = &headerInjector{
        base: originalTransport,
    }
    
    // ... rest of initialization
}

type headerInjector struct {
    base http.RoundTripper
}

func (h *headerInjector) RoundTrip(req *http.Request) (*http.Response, error) {
    if envHeaders := os.Getenv("WANDB_HTTP_HEADERS"); envHeaders != "" {
        for _, header := range strings.Split(envHeaders, ",") {
            parts := strings.SplitN(header, ":", 2)
            if len(parts) == 2 {
                req.Header.Set(strings.TrimSpace(parts[0]), strings.TrimSpace(parts[1]))
            }
        }
    }
    return h.base.RoundTrip(req)
}
```

### Python Implementation

#### Approach 1: Modify Internal API (Recommended)
```python
# In internal_api.py
import os
import json

def upload_file(self, url, file, callback=None, extra_headers=None):
    extra_headers = extra_headers.copy() if extra_headers else {}
    
    # Add environment-based headers
    env_headers = os.environ.get('WANDB_HTTP_HEADERS')
    if env_headers:
        try:
            # Support JSON format
            custom_headers = json.loads(env_headers)
            extra_headers.update(custom_headers)
        except json.JSONDecodeError:
            # Support simple format: "Header1:Value1,Header2:Value2"
            for header in env_headers.split(','):
                parts = header.split(':', 1)
                if len(parts) == 2:
                    extra_headers[parts[0].strip()] = parts[1].strip()
    
    # ... rest of the method
```

```python
def download_file(self, url):
    http_headers = _thread_local_api_settings.headers or {}
    
    # Add environment-based headers
    env_headers = os.environ.get('WANDB_HTTP_HEADERS')
    if env_headers:
        try:
            custom_headers = json.loads(env_headers)
            http_headers.update(custom_headers)
        except json.JSONDecodeError:
            for header in env_headers.split(','):
                parts = header.split(':', 1)
                if len(parts) == 2:
                    http_headers[parts[0].strip()] = parts[1].strip()
    
    # ... rest of the method
```

#### Approach 2: Configure Session Object
```python
# In internal_api.py __init__ method
def __init__(self, ...):
    # ... existing initialization ...
    
    # Configure session with environment headers
    self._upload_file_session = requests.Session()
    
    env_headers = os.environ.get('WANDB_HTTP_HEADERS')
    if env_headers:
        try:
            custom_headers = json.loads(env_headers)
            self._upload_file_session.headers.update(custom_headers)
        except json.JSONDecodeError:
            for header in env_headers.split(','):
                parts = header.split(':', 1)
                if len(parts) == 2:
                    self._upload_file_session.headers[parts[0].strip()] = parts[1].strip()
```

## Environment Variable Format Options

### Option 1: JSON Format (Recommended)
```bash
export WANDB_HTTP_HEADERS='{"X-Custom-Header": "value", "X-Another-Header": "value2"}'
```

### Option 2: Simple Format
```bash
export WANDB_HTTP_HEADERS="X-Custom-Header:value,X-Another-Header:value2"
```

### Option 3: Multiple Environment Variables
```bash
export WANDB_HTTP_HEADER_X_CUSTOM="value"
export WANDB_HTTP_HEADER_X_ANOTHER="value2"
```

## Security Considerations

1. **Avoid logging sensitive headers** - Ensure custom headers containing tokens or credentials are not logged
2. **Validate header names** - Prevent header injection attacks
3. **Document restricted headers** - Some headers like `Host`, `Content-Length` should not be overridden
4. **Consider scope** - Headers should only apply to signed URL operations, not API calls

## Testing Recommendations

1. **Unit Tests** - Test header parsing from environment variables
2. **Integration Tests** - Verify headers are correctly sent with requests
3. **Edge Cases** - Test with malformed environment variables
4. **Performance** - Ensure header parsing doesn't impact upload/download performance

## Implementation Priority

1. **High Priority**: 
   - `core/internal/filetransfer/file_transfer_default.go` (Go)
   - `wandb/sdk/internal/internal_api.py` (Python)

2. **Medium Priority**:
   - `wandb/filesync/upload_job.py` (Python)
   - `core/pkg/artifacts/downloader.go` (Go)

3. **Low Priority**:
   - Additional artifact handlers
   - Storage-specific handlers (S3, GCS, Azure)

## Conclusion

Both Go and Python implementations currently support custom headers but don't have environment variable-based header injection. The recommended approach is to:

1. Use JSON format for environment variable (`WANDB_HTTP_HEADERS`)
2. Parse and inject headers at the HTTP client level
3. Ensure headers are applied to both upload and download operations
4. Add proper error handling and validation
5. Document the feature for users