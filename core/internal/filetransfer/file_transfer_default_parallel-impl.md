# Parallel File Transfer Implementation Design

## Key Design Decisions
- **No HEAD request needed**: Use `task.Size` field which already contains file size
- **Keep logic in `file_transfer_default.go`**: Implement directly in existing file for initial version
- **Use existing retry**: Leverage `retryablehttp.Client` instead of custom retry logic  
- **Simple progress tracking**: Single writer goroutine, no locks needed initially

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Core Components](#core-components)
3. [Implementation Tasks](#implementation-tasks)
4. [Refactoring Plan](#refactoring-plan)
5. [Testing Strategy](#testing-strategy)

## Architecture Overview

### Current State Analysis

**Go Serial Download** (`file_transfer_default.go:97`)
```go
func (ft *DefaultFileTransfer) Download(task *DefaultDownloadTask) error {
    resp, err := ft.client.Get(task.Url)
    if err != nil {
        return err
    }
    file, err := os.Create(task.Path)
    if err != nil {
        return err
    }
    _, err = io.Copy(file, resp.Body)  // Single-threaded copy
    return err
}
```

**Python Parallel Download** (Reference Implementation)
- File size threshold: 2GB (S3_MIN_MULTI_UPLOAD_SIZE)
- Part size: 100MB chunks
- HTTP chunk size: 1MB for streaming
- Uses ThreadPoolExecutor with queue-based file writing

### Proposed Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  Download Task  │───▶│ Size Check       │───▶│ Parallel/Serial │
│                 │    │ (2GB threshold)  │    │ Decision        │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                                         │
                          ┌─────────────────────────────┴──────────────────┐
                          ▼                                                ▼
                ┌─────────────────┐                            ┌─────────────────┐
                │ Parallel Flow   │                            │ Serial Flow     │
                │                 │                            │ (existing)      │
                └─────────────────┘                            └─────────────────┘
                          │
           ┌──────────────┼──────────────┐
           ▼              ▼              ▼
    ┌───────────┐  ┌───────────┐  ┌───────────┐
    │  Worker 1 │  │  Worker 2 │  │  Worker N │
    │  Range:   │  │  Range:   │  │  Range:   │
    │  0-99MB   │  │ 100-199MB │  │  ...      │
    └─────┬─────┘  └─────┬─────┘  └─────┬─────┘
          │              │              │
          └──────────────┼──────────────┘
                         ▼
                ┌─────────────────┐
                │  File Writer    │
                │  (Queue-based)  │
                └─────────────────┘
```

### Constants and Thresholds

```go
const (
    // Download thresholds (matching Python implementation)
    S3MinMultiDownloadSize = 2 << 30   // 2 GiB
    S3DefaultDownloadChunkSize = 100 << 20  // 100 MiB
    S3DefaultHTTPChunkSize = 1 << 20   // 1 MiB
    
    // Queue settings
    DownloadQueueSize = 500  // Max buffered chunks
)
```

## Core Components

### 1. Simplified Parallel Download (within file_transfer_default.go)

```go
// Add these methods directly to DefaultFileTransfer in file_transfer_default.go

// shouldUseParallelDownload checks if file meets threshold for parallel download
func (ft *DefaultFileTransfer) shouldUseParallelDownload(task *DefaultDownloadTask) bool {
    // Use task.Size which already contains the file size
    // No need for HEAD request
    return task.Size >= S3MinMultiDownloadSize && task.Size > 0
}

// downloadParallel performs parallel download
func (ft *DefaultFileTransfer) downloadParallel(task *DefaultDownloadTask) error {
    ft.logger.Debug("parallel download starting", 
        "path", task.Path, 
        "url", task.Url, 
        "size", task.Size)
    
    // Calculate parts based on task.Size
    parts := ft.calculateDownloadParts(task.Size)
    numWorkers := min(runtime.NumCPU(), len(parts))
    
    // Create output file
    dir := path.Dir(task.Path)
    if err := os.MkdirAll(dir, os.ModePerm); err != nil {
        return err
    }
    
    file, err := os.Create(task.Path)
    if err != nil {
        return err
    }
    defer file.Close()
    
    // Setup channels and context
    ctx := context.Background()
    if task.Context != nil {
        ctx = task.Context
    }
    
    chunkQueue := make(chan ChunkData, DownloadQueueSize)
    g, ctx := errgroup.WithContext(ctx)
    
    // Start file writer goroutine
    g.Go(func() error {
        return ft.writeChunksToFile(ctx, file, chunkQueue, task)
    })
    
    // Start download workers
    workerTasks := ft.splitDownloadTasks(parts, numWorkers)
    for i, workerParts := range workerTasks {
        workerID := i
        taskParts := workerParts
        
        g.Go(func() error {
            return ft.downloadWorker(ctx, workerID, task, taskParts, chunkQueue)
        })
    }
    
    // Wait for all downloads to complete
    downloadErr := g.Wait()
    
    // Signal writer to stop
    close(chunkQueue)
    
    return downloadErr
}
```

### 2. Simplified Download Worker (No custom retry)

```go
// DownloadPart represents a chunk to download
type DownloadPart struct {
    PartNumber int
    StartByte  int64
    EndByte    int64
    Size       int64
}

// downloadWorker handles downloading parts for a worker
// This method is added to DefaultFileTransfer
func (ft *DefaultFileTransfer) downloadWorker(
    ctx context.Context,
    workerID int,
    task *DefaultDownloadTask,
    parts []DownloadPart,
    chunkQueue chan<- ChunkData,
) error {
    for _, part := range parts {
        if err := ft.downloadPart(ctx, task, part, chunkQueue); err != nil {
            return fmt.Errorf("worker %d failed on part %d: %w", workerID, part.PartNumber, err)
        }
    }
    return nil
}

// downloadPart downloads a single part using Range header
// The retryablehttp.Client handles retries automatically
func (ft *DefaultFileTransfer) downloadPart(
    ctx context.Context,
    task *DefaultDownloadTask,
    part DownloadPart,
    chunkQueue chan<- ChunkData,
) error {
    // Create range request: "bytes=0-104857599" (0-99MB)
    rangeHeader := fmt.Sprintf("bytes=%d-%d", part.StartByte, part.EndByte)
    
    req, err := retryablehttp.NewRequest(http.MethodGet, task.Url, nil)
    if err != nil {
        return err
    }
    req.Header.Set("Range", rangeHeader)
    
    // Add original headers from task
    for _, header := range task.Headers {
        parts := strings.SplitN(header, ":", 2)
        if len(parts) == 2 {
            req.Header.Set(parts[0], parts[1])
        }
    }
    
    // retryablehttp.Client handles retries automatically
    resp, err := ft.client.Do(req.WithContext(ctx))
    if err != nil {
        return err
    }
    defer resp.Body.Close()
    
    if resp.StatusCode != http.StatusPartialContent {
        return fmt.Errorf("expected 206 Partial Content, got %d", resp.StatusCode)
    }
    
    // Stream response in chunks
    offset := part.StartByte
    buffer := make([]byte, S3DefaultHTTPChunkSize) // 1MB buffer
    
    for {
        select {
        case <-ctx.Done():
            return ctx.Err()
        default:
        }
        
        n, err := resp.Body.Read(buffer)
        if n > 0 {
            chunk := ChunkData{
                Offset: offset,
                Data:   make([]byte, n),
            }
            copy(chunk.Data, buffer[:n])
            
            select {
            case chunkQueue <- chunk:
                offset += int64(n)
            case <-ctx.Done():
                return ctx.Err()
            }
        }
        
        if err == io.EOF {
            break
        } else if err != nil {
            return err
        }
    }
    
    return nil
}
```

### 3. Simplified File Writer (No locks needed for single writer)

```go
// ChunkData represents downloaded data with its file offset
type ChunkData struct {
    Offset int64
    Data   []byte
}

// writeChunksToFile handles writing chunks to file
// Single goroutine writer - no locks needed
// Added to DefaultFileTransfer
func (ft *DefaultFileTransfer) writeChunksToFile(
    ctx context.Context,
    file *os.File,
    chunkQueue <-chan ChunkData,
    task *DefaultDownloadTask,
) error {
    writtenBytes := int64(0)
    
    for {
        select {
        case <-ctx.Done():
            return ctx.Err()
        case chunk, ok := <-chunkQueue:
            if !ok {
                // Channel closed, all chunks written
                return nil
            }
            
            // Seek to correct position (creates sparse file)
            if _, err := file.Seek(chunk.Offset, io.SeekStart); err != nil {
                return fmt.Errorf("failed to seek to offset %d: %w", chunk.Offset, err)
            }
            
            // Write chunk data
            if _, err := file.Write(chunk.Data); err != nil {
                return fmt.Errorf("failed to write chunk at offset %d: %w", chunk.Offset, err)
            }
            
            // Update progress (optional - can skip in first iteration)
            writtenBytes += int64(len(chunk.Data))
            if task.ProgressCallback != nil {
                // No locks needed - single writer goroutine
                task.ProgressCallback(int(writtenBytes), int(task.Size))
            }
            
            // Update file transfer stats (optional - can skip in first iteration)
            if ft.fileTransferStats != nil {
                ft.fileTransferStats.UpdateDownloadStats(FileDownloadInfo{
                    FileKind:        task.FileKind,
                    Path:            task.Path,
                    DownloadedBytes: writtenBytes,
                    TotalBytes:      task.Size,
                })
            }
        }
    }
}
```

### 4. Helper Functions

```go
// calculateDownloadParts splits file into parts for parallel download
func (ft *DefaultFileTransfer) calculateDownloadParts(fileSize int64) []DownloadPart {
    chunkSize := ft.getDownloadChunkSize(fileSize)
    numParts := int(fileSize / chunkSize)
    if fileSize%chunkSize != 0 {
        numParts++
    }
    
    parts := make([]DownloadPart, numParts)
    for i := 0; i < numParts; i++ {
        startByte := int64(i) * chunkSize
        endByte := min(startByte+chunkSize-1, fileSize-1)
        
        parts[i] = DownloadPart{
            PartNumber: i + 1,
            StartByte:  startByte,
            EndByte:    endByte,
            Size:       endByte - startByte + 1,
        }
    }
    
    return parts
}

func (ft *DefaultFileTransfer) getDownloadChunkSize(fileSize int64) int64 {
    if fileSize < S3DefaultDownloadChunkSize*S3MaxParts {
        return S3DefaultDownloadChunkSize
    }
    // Calculate larger chunk size if needed
    chunkSize := int64(math.Ceil(float64(fileSize) / float64(S3MaxParts)))
    return int64(math.Ceil(float64(chunkSize)/4096) * 4096)
}

// splitDownloadTasks distributes parts among workers
// Reuses pattern from multipart.go
func (ft *DefaultFileTransfer) splitDownloadTasks(parts []DownloadPart, numWorkers int) [][]DownloadPart {
    partsPerWorker := len(parts) / numWorkers
    workersWithOneMorePart := len(parts) % numWorkers
    
    workerTasks := make([][]DownloadPart, numWorkers)
    partIndex := 0
    
    for i := 0; i < numWorkers; i++ {
        workerPartCount := partsPerWorker
        if i < workersWithOneMorePart {
            workerPartCount++
        }
        
        workerTasks[i] = parts[partIndex : partIndex+workerPartCount]
        partIndex += workerPartCount
    }
    
    return workerTasks
}
```

## Implementation Tasks

### Phase 1: Core Implementation in file_transfer_default.go

**1.1 Add constants at the top of file_transfer_default.go**

```go
const (
    // Parallel download thresholds
    S3MinMultiDownloadSize = 2 << 30        // 2 GiB
    S3DefaultDownloadChunkSize = 100 << 20  // 100 MiB
    S3DefaultHTTPChunkSize = 1 << 20        // 1 MiB
    S3MaxParts = 10000
    DownloadQueueSize = 500                 // Max buffered chunks
)
```

**1.2 Add ChunkData struct**

```go
// ChunkData represents downloaded data with its file offset
type ChunkData struct {
    Offset int64
    Data   []byte
}

// DownloadPart represents a chunk to download
type DownloadPart struct {
    PartNumber int
    StartByte  int64
    EndByte    int64
    Size       int64
}
```

**1.3 Modify existing Download method**

```go
func (ft *DefaultFileTransfer) Download(task *DefaultDownloadTask) error {
    ft.logger.Debug("default file transfer: downloading file", "path", task.Path, "url", task.Url)
    
    // Check if we should use parallel download based on task.Size
    if ft.shouldUseParallelDownload(task) {
        ft.logger.Debug("using parallel download", "size", task.Size)
        return ft.downloadParallel(task)
    }
    
    // Fallback to serial download for small files
    ft.logger.Debug("using serial download", "size", task.Size)
    return ft.downloadSerial(task)
}

// Rename current Download implementation to downloadSerial
func (ft *DefaultFileTransfer) downloadSerial(task *DefaultDownloadTask) error {
    // Move existing implementation (lines 98-150) here
    dir := path.Dir(task.Path)
    // ... rest of current implementation ...
}
```

### Phase 2: Add All Parallel Download Methods

**2.1 Add all methods to DefaultFileTransfer in file_transfer_default.go**

```go
// Add all these methods to the existing file_transfer_default.go file

func (ft *DefaultFileTransfer) shouldUseParallelDownload(task *DefaultDownloadTask) bool {
    return task.Size >= S3MinMultiDownloadSize && task.Size > 0
}

func (ft *DefaultFileTransfer) downloadParallel(task *DefaultDownloadTask) error {
    // Implementation from Core Components section
    // See section "1. Simplified Parallel Download"
}

func (ft *DefaultFileTransfer) downloadWorker(
    ctx context.Context,
    workerID int,
    task *DefaultDownloadTask,
    parts []DownloadPart,
    chunkQueue chan<- ChunkData,
) error {
    // Implementation from Core Components section
    // See section "2. Simplified Download Worker"
}

func (ft *DefaultFileTransfer) downloadPart(
    ctx context.Context,
    task *DefaultDownloadTask,
    part DownloadPart,
    chunkQueue chan<- ChunkData,
) error {
    // Implementation from Core Components section
    // See section "2. Simplified Download Worker"
}

func (ft *DefaultFileTransfer) writeChunksToFile(
    ctx context.Context,
    file *os.File,
    chunkQueue <-chan ChunkData,
    task *DefaultDownloadTask,
) error {
    // Implementation from Core Components section
    // See section "3. Simplified File Writer"
}

func (ft *DefaultFileTransfer) calculateDownloadParts(fileSize int64) []DownloadPart {
    // Implementation from Core Components section
    // See section "4. Helper Functions"
}

func (ft *DefaultFileTransfer) getDownloadChunkSize(fileSize int64) int64 {
    // Implementation from Core Components section
    // See section "4. Helper Functions"
}

func (ft *DefaultFileTransfer) splitDownloadTasks(parts []DownloadPart, numWorkers int) [][]DownloadPart {
    // Implementation from Core Components section
    // See section "4. Helper Functions"
}
```

### Phase 3: Required Imports

**3.1 Add necessary imports to file_transfer_default.go**

```go
import (
    "context"
    "fmt"
    "io"
    "math"
    "net/http"
    "os"
    "path"
    "runtime"
    "strings"
    
    "github.com/hashicorp/go-retryablehttp"
    "github.com/wandb/wandb/core/internal/observability"
    "github.com/wandb/wandb/core/internal/wboperation"
    "golang.org/x/sync/errgroup"  // New import for parallel execution
)
```

### Phase 4: Testing Integration

**4.1 Unit Test Structure**

```go
func TestParallelDownload(t *testing.T) {
    // Create test server with range request support
    server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        if r.Method == http.MethodHead {
            w.Header().Set("Content-Length", "209715200") // 200MB
            w.WriteHeader(http.StatusOK)
            return
        }
        
        if r.Method == http.MethodGet {
            rangeHeader := r.Header.Get("Range")
            if rangeHeader != "" {
                // Parse range and serve partial content
                // Implementation details...
                w.WriteHeader(http.StatusPartialContent)
            } else {
                w.WriteHeader(http.StatusOK)
            }
            // Serve test data...
        }
    }))
    defer server.Close()
    
    // Test parallel download
    task := &DefaultDownloadTask{
        Path: "/tmp/test-parallel-download",
        Url:  server.URL,
    }
    
    ft := NewDefaultFileTransfer(client, logger, stats)
    err := ft.Download(task)
    assert.NoError(t, err)
    
    // Verify file content and size
    stat, err := os.Stat(task.Path)
    assert.NoError(t, err)
    assert.Equal(t, int64(209715200), stat.Size())
}
```

## Future Refactoring Plan (After Initial Implementation)

After the parallel download is working in `file_transfer_default.go`, consider these refactoring opportunities:

### 1. Extract Common Worker Pool Pattern

Both `multipart.go` (for hashing) and the new parallel download use similar worker pool patterns. A future refactoring could extract:

```go
// worker_pool.go - Shared worker pool functionality
type WorkerPool struct {
    numWorkers int
    logger     *observability.CoreLogger
}

// Common task distribution logic
func SplitTasks[T any](tasks []T, numWorkers int) [][]T {
    tasksPerWorker := len(tasks) / numWorkers
    workersWithOneMoreTask := len(tasks) % numWorkers
    
    result := make([][]T, numWorkers)
    taskIndex := 0
    
    for i := 0; i < numWorkers; i++ {
        workerTaskCount := tasksPerWorker
        if i < workersWithOneMoreTask {
            workerTaskCount++
        }
        result[i] = tasks[taskIndex : taskIndex+workerTaskCount]
        taskIndex += workerTaskCount
    }
    return result
}
```

### 2. Unified Progress Tracking

Create a shared progress tracker that can be used for both uploads and downloads:

```go
// progress_tracker.go
type ProgressTracker struct {
    total        int64
    processed    int64
    callback     func(int, int)
    stats        FileTransferStats
}

func (pt *ProgressTracker) UpdateProgress(bytes int64) {
    pt.processed += bytes
    if pt.callback != nil {
        pt.callback(int(pt.processed), int(pt.total))
    }
}
```

### 3. Share Chunk Size Calculation

Both upload and download need similar chunk size calculations:

```go
// chunk_calculator.go
func CalculateOptimalChunkSize(fileSize int64, defaultChunkSize int64, maxParts int) int64 {
    if fileSize < defaultChunkSize*int64(maxParts) {
        return defaultChunkSize
    }
    chunkSize := int64(math.Ceil(float64(fileSize) / float64(maxParts)))
    return int64(math.Ceil(float64(chunkSize)/4096) * 4096)
}
```

### 4. FileDownloadInfo Structure

Note: The code references `FileDownloadInfo` but it may not exist. You might need to add:

```go
// Add to file_transfer_stats.go or relevant location
type FileDownloadInfo struct {
    FileKind        RunFileKind
    Path            string
    DownloadedBytes int64
    TotalBytes      int64
}

// Add method to FileTransferStats interface
type FileTransferStats interface {
    UpdateUploadStats(info FileUploadInfo)
    UpdateDownloadStats(info FileDownloadInfo)  // New method
}
```

## Testing Strategy

### 1. Unit Tests

**Test File Size Thresholds**
```go
func TestShouldUseParallelDownload(t *testing.T) {
    tests := []struct {
        name           string
        contentLength  int64
        expectedParallel bool
    }{
        {"Small file", 1024 * 1024, false},           // 1MB
        {"Threshold file", S3MinMultiDownloadSize, true}, // 2GB
        {"Large file", 5 * S3MinMultiDownloadSize, true}, // 10GB
    }
    
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            // Test implementation
        })
    }
}
```

**Test Range Request Handling**
```go
func TestRangeRequestSupport(t *testing.T) {
    server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        rangeHeader := r.Header.Get("Range")
        assert.Contains(t, rangeHeader, "bytes=")
        
        w.Header().Set("Content-Range", "bytes 0-1023/2048")
        w.WriteHeader(http.StatusPartialContent)
        w.Write(make([]byte, 1024))
    }))
    defer server.Close()
    
    // Test range request handling
}
```

### 2. Integration Tests

**End-to-End Download Test**
```go
func TestE2EParallelDownload(t *testing.T) {
    // Create large test file
    testData := make([]byte, 3*S3MinMultiDownloadSize) // 6GB
    // Fill with test pattern
    
    server := createRangeServerWithData(testData)
    defer server.Close()
    
    // Test download
    downloadPath := filepath.Join(t.TempDir(), "large-file")
    task := &DefaultDownloadTask{Path: downloadPath, Url: server.URL}
    
    ft := NewDefaultFileTransfer(client, logger, stats)
    err := ft.Download(task)
    assert.NoError(t, err)
    
    // Verify downloaded file matches original
    downloadedData, err := os.ReadFile(downloadPath)
    assert.NoError(t, err)
    assert.Equal(t, testData, downloadedData)
}
```

### 3. Benchmarks

```go
func BenchmarkSerialVsParallelDownload(b *testing.B) {
    testSizes := []int64{
        100 * 1024 * 1024,      // 100MB
        1024 * 1024 * 1024,     // 1GB  
        3 * 1024 * 1024 * 1024, // 3GB
    }
    
    for _, size := range testSizes {
        b.Run(fmt.Sprintf("Serial_%dMB", size/1024/1024), func(b *testing.B) {
            // Benchmark serial download
        })
        
        b.Run(fmt.Sprintf("Parallel_%dMB", size/1024/1024), func(b *testing.B) {
            // Benchmark parallel download
        })
    }
}
```

### 4. Error Scenarios

- Network interruption during download
- Server not supporting range requests (fallback to serial)
- Partial download failure with retry
- Context cancellation
- Disk space exhaustion
- Permission errors

This comprehensive design provides a clear roadmap for implementing parallel downloads in Go while maintaining compatibility with existing code and following established patterns from the multipart upload implementation.