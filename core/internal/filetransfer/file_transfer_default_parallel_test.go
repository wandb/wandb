package filetransfer

import (
	"context"
	"fmt"
	"math"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestShouldUseParallelDownload(t *testing.T) {
	ft := &DefaultFileTransfer{
		logger: observability.NewNoOpLogger(),
	}

	tests := []struct {
		name     string
		fileSize int64
		expected bool
	}{
		{
			name:     "small file (1MB)",
			fileSize: 1 << 20, // 1MB
			expected: false,
		},
		{
			name:     "medium file (1GB)",
			fileSize: 1 << 30, // 1GB
			expected: false,
		},
		{
			name:     "exactly at threshold (2GB)",
			fileSize: s3MinMultiDownloadSize, // 2GB
			expected: true,
		},
		{
			name:     "large file (3GB)",
			fileSize: 3 << 30, // 3GB
			expected: true,
		},
		{
			name:     "zero size",
			fileSize: 0,
			expected: false,
		},
		{
			name:     "negative size",
			fileSize: -1,
			expected: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			task := &DefaultDownloadTask{
				Size: tt.fileSize,
			}
			result := ft.shouldUseParallelDownload(task)
			assert.Equal(t, tt.expected, result)
		})
	}
}

func TestGetDownloadChunkSize(t *testing.T) {
	ft := &DefaultFileTransfer{
		logger: observability.NewNoOpLogger(),
	}

	defaultChunkSize := int64(s3DefaultDownloadChunkSize)

	fileSizes := []int64{
		// Uses the default chunk size
		defaultChunkSize / 100,
		defaultChunkSize,
		defaultChunkSize + 1,
		10000 * defaultChunkSize,
		// Uses the next largest chunk size (+4096)
		10000*defaultChunkSize + 1,
		10000 * (defaultChunkSize + 4096),
		// Uses the next-next largest chunk size (+2*4096)
		10000*(defaultChunkSize+4096) + 1,
	}

	for _, fileSize := range fileSizes {
		t.Run(fmt.Sprintf("fileSize=%d", fileSize), func(t *testing.T) {
			chunkSize := ft.getDownloadChunkSize(fileSize)
			assert.GreaterOrEqual(t, chunkSize, defaultChunkSize)
			// Chunk size should always be a multiple of 4096
			assert.True(t, chunkSize%4096 == 0)
			// Chunk size is always sufficient to download the file in no more than s3MaxParts chunks
			assert.True(t, chunkSize*s3MaxParts >= fileSize)
			if chunkSize > defaultChunkSize {
				// If chunk size is greater than the default, we should be downloading s3MaxParts chunks
				chunksUsed := int(math.Ceil(float64(fileSize) / float64(chunkSize)))
				assert.Equal(t, s3MaxParts, chunksUsed)
			}
		})
	}
}

func TestCalculateDownloadParts(t *testing.T) {
	ft := &DefaultFileTransfer{
		logger: observability.NewNoOpLogger(),
	}

	t.Run("exact multiple of chunk size", func(t *testing.T) {
		fileSize := int64(300 << 20) // 300MB (3 chunks of 100MB)
		parts := ft.calculateDownloadParts(fileSize)
		
		assert.Len(t, parts, 3)
		
		// Check first part
		assert.Equal(t, 1, parts[0].PartNumber)
		assert.Equal(t, int64(0), parts[0].StartByte)
		assert.Equal(t, int64(100<<20-1), parts[0].EndByte)
		assert.Equal(t, int64(100<<20), parts[0].Size)
		
		// Check second part
		assert.Equal(t, 2, parts[1].PartNumber)
		assert.Equal(t, int64(100<<20), parts[1].StartByte)
		assert.Equal(t, int64(200<<20-1), parts[1].EndByte)
		assert.Equal(t, int64(100<<20), parts[1].Size)
		
		// Check third part
		assert.Equal(t, 3, parts[2].PartNumber)
		assert.Equal(t, int64(200<<20), parts[2].StartByte)
		assert.Equal(t, int64(300<<20-1), parts[2].EndByte)
		assert.Equal(t, int64(100<<20), parts[2].Size)
	})

	t.Run("not exact multiple of chunk size", func(t *testing.T) {
		fileSize := int64(250 << 20) // 250MB (2 full chunks + 50MB)
		parts := ft.calculateDownloadParts(fileSize)
		
		assert.Len(t, parts, 3)
		
		// Check last part is smaller
		assert.Equal(t, 3, parts[2].PartNumber)
		assert.Equal(t, int64(200<<20), parts[2].StartByte)
		assert.Equal(t, int64(250<<20-1), parts[2].EndByte)
		assert.Equal(t, int64(50<<20), parts[2].Size)
	})

	t.Run("single part file", func(t *testing.T) {
		fileSize := int64(50 << 20) // 50MB (less than one chunk)
		parts := ft.calculateDownloadParts(fileSize)
		
		assert.Len(t, parts, 1)
		assert.Equal(t, 1, parts[0].PartNumber)
		assert.Equal(t, int64(0), parts[0].StartByte)
		assert.Equal(t, fileSize-1, parts[0].EndByte)
		assert.Equal(t, fileSize, parts[0].Size)
	})

	t.Run("verify sequential part numbers", func(t *testing.T) {
		fileSize := int64(1100 << 20) // 1100MB (11 chunks)
		parts := ft.calculateDownloadParts(fileSize)
		
		assert.Len(t, parts, 11)
		for i := 0; i < len(parts)-1; i++ {
			assert.Equal(t, parts[i].PartNumber+1, parts[i+1].PartNumber)
			// Verify parts are contiguous
			assert.Equal(t, parts[i].EndByte+1, parts[i+1].StartByte)
		}
	})
}

func TestSplitDownloadTasks(t *testing.T) {
	ft := &DefaultFileTransfer{
		logger: observability.NewNoOpLogger(),
	}

	t.Run("even distribution", func(t *testing.T) {
		// 6 parts, 2 workers -> each worker gets 3 parts
		parts := make([]downloadPart, 6)
		for i := 0; i < 6; i++ {
			parts[i] = downloadPart{PartNumber: i + 1}
		}
		
		tasks := ft.splitDownloadTasks(parts, 2)
		require.Len(t, tasks, 2)
		
		assert.Len(t, tasks[0], 3)
		assert.Equal(t, 1, tasks[0][0].PartNumber)
		assert.Equal(t, 3, tasks[0][2].PartNumber)
		
		assert.Len(t, tasks[1], 3)
		assert.Equal(t, 4, tasks[1][0].PartNumber)
		assert.Equal(t, 6, tasks[1][2].PartNumber)
	})

	t.Run("uneven distribution", func(t *testing.T) {
		// 11 parts, 3 workers -> 2 workers get 4 parts, 1 worker gets 3 parts
		parts := make([]downloadPart, 11)
		for i := 0; i < 11; i++ {
			parts[i] = downloadPart{PartNumber: i + 1}
		}
		
		tasks := ft.splitDownloadTasks(parts, 3)
		require.Len(t, tasks, 3)
		
		// Worker 0: parts 1-4 (4 parts)
		assert.Len(t, tasks[0], 4)
		assert.Equal(t, 1, tasks[0][0].PartNumber)
		assert.Equal(t, 4, tasks[0][3].PartNumber)
		
		// Worker 1: parts 5-8 (4 parts)
		assert.Len(t, tasks[1], 4)
		assert.Equal(t, 5, tasks[1][0].PartNumber)
		assert.Equal(t, 8, tasks[1][3].PartNumber)
		
		// Worker 2: parts 9-11 (3 parts)
		assert.Len(t, tasks[2], 3)
		assert.Equal(t, 9, tasks[2][0].PartNumber)
		assert.Equal(t, 11, tasks[2][2].PartNumber)
	})

	t.Run("single worker", func(t *testing.T) {
		// 7 parts, 1 worker -> all parts go to the single worker
		parts := make([]downloadPart, 7)
		for i := 0; i < 7; i++ {
			parts[i] = downloadPart{PartNumber: i + 1}
		}
		
		tasks := ft.splitDownloadTasks(parts, 1)
		require.Len(t, tasks, 1)
		
		assert.Len(t, tasks[0], 7)
		assert.Equal(t, 1, tasks[0][0].PartNumber)
		assert.Equal(t, 7, tasks[0][6].PartNumber)
	})

	t.Run("more workers than parts", func(t *testing.T) {
		// 3 parts, 5 workers -> first 3 workers get 1 part each, last 2 get none
		parts := make([]downloadPart, 3)
		for i := 0; i < 3; i++ {
			parts[i] = downloadPart{PartNumber: i + 1}
		}
		
		tasks := ft.splitDownloadTasks(parts, 5)
		require.Len(t, tasks, 5)
		
		// First 3 workers get 1 part each
		for i := 0; i < 3; i++ {
			assert.Len(t, tasks[i], 1)
			assert.Equal(t, i+1, tasks[i][0].PartNumber)
		}
		
		// Last 2 workers get no parts
		assert.Len(t, tasks[3], 0)
		assert.Len(t, tasks[4], 0)
	})

	t.Run("verify all parts are distributed", func(t *testing.T) {
		// 17 parts, 4 workers
		parts := make([]downloadPart, 17)
		for i := 0; i < 17; i++ {
			parts[i] = downloadPart{PartNumber: i + 1}
		}
		
		tasks := ft.splitDownloadTasks(parts, 4)
		
		// Collect all distributed parts
		var allParts []downloadPart
		for _, workerParts := range tasks {
			allParts = append(allParts, workerParts...)
		}
		
		// Verify all parts are distributed exactly once
		assert.Len(t, allParts, 17)
		for i := 0; i < 17; i++ {
			assert.Equal(t, i+1, allParts[i].PartNumber)
		}
	})
}

func TestParallelDownloadIntegration(t *testing.T) {
	// Skip this test in short mode as it involves network operations
	if testing.Short() {
		t.Skip("Skipping integration test in short mode")
	}

	// Create test data (3GB to trigger parallel download)
	testDataSize := int64(3 << 30) // 3GB
	
	// Create a test server that supports range requests
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		rangeHeader := r.Header.Get("Range")
		
		if rangeHeader == "" {
			// Full file request (should not happen in parallel mode)
			t.Error("Unexpected full file request in parallel mode")
			http.Error(w, "Range header required", http.StatusBadRequest)
			return
		}
		
		// Parse range header (simplified for testing)
		var start, end int64
		_, err := fmt.Sscanf(rangeHeader, "bytes=%d-%d", &start, &end)
		if err != nil {
			http.Error(w, "Invalid range header", http.StatusBadRequest)
			return
		}
		
		// Calculate response size
		responseSize := end - start + 1
		
		// Set headers for partial content
		w.Header().Set("Content-Range", fmt.Sprintf("bytes %d-%d/%d", start, end, testDataSize))
		w.Header().Set("Content-Length", fmt.Sprintf("%d", responseSize))
		w.WriteHeader(http.StatusPartialContent)
		
		// Write dummy data (just zeros for testing)
		written := int64(0)
		buffer := make([]byte, 1024*1024) // 1MB buffer
		for written < responseSize {
			toWrite := min(int64(len(buffer)), responseSize-written)
			n, err := w.Write(buffer[:toWrite])
			if err != nil {
				return
			}
			written += int64(n)
		}
	}))
	defer server.Close()

	// Create temp directory for download
	tempDir := t.TempDir()
	downloadPath := filepath.Join(tempDir, "test-parallel-download")

	// Create file transfer with client
	client := retryablehttp.NewClient()
	client.RetryMax = 1
	ft := NewDefaultFileTransfer(
		client,
		observability.NewNoOpLogger(),
		nil, // No stats for this test
	)

	// Create download task
	task := &DefaultDownloadTask{
		Path: downloadPath,
		Url:  server.URL,
		Size: testDataSize,
		Context: context.Background(),
	}

	// Verify it will use parallel download
	assert.True(t, ft.shouldUseParallelDownload(task))

	// Perform download
	err := ft.Download(task)
	require.NoError(t, err)

	// Verify file was created with correct size
	stat, err := os.Stat(downloadPath)
	require.NoError(t, err)
	assert.Equal(t, testDataSize, stat.Size())
}

func TestDownloadPartWithRangeRequest(t *testing.T) {
	// Create a test server that verifies range requests
	rangeRequests := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		rangeHeader := r.Header.Get("Range")
		
		// Verify range header is present
		assert.NotEmpty(t, rangeHeader)
		rangeRequests++
		
		// Parse range header
		var start, end int64
		_, err := fmt.Sscanf(rangeHeader, "bytes=%d-%d", &start, &end)
		require.NoError(t, err)
		
		// Verify it's requesting the expected range (0-99 for first 100 bytes)
		if rangeRequests == 1 {
			assert.Equal(t, int64(0), start)
			assert.Equal(t, int64(99), end)
		}
		
		// Send partial content response
		responseData := make([]byte, end-start+1)
		for i := range responseData {
			responseData[i] = byte(i % 256)
		}
		
		w.Header().Set("Content-Range", fmt.Sprintf("bytes %d-%d/1000", start, end))
		w.WriteHeader(http.StatusPartialContent)
		w.Write(responseData)
	}))
	defer server.Close()

	client := retryablehttp.NewClient()
	client.RetryMax = 0
	ft := NewDefaultFileTransfer(
		client,
		observability.NewNoOpLogger(),
		nil,
	)

	// Test downloading a single part
	ctx := context.Background()
	task := &DefaultDownloadTask{
		Url: server.URL,
	}
	part := downloadPart{
		PartNumber: 1,
		StartByte:  0,
		EndByte:    99,
		Size:       100,
	}

	chunkQueue := make(chan chunkData, 10)
	err := ft.downloadPart(ctx, task, part, chunkQueue)
	require.NoError(t, err)

	// Verify we got the data
	select {
	case chunk := <-chunkQueue:
		assert.Equal(t, int64(0), chunk.Offset)
		assert.Len(t, chunk.Data, 100)
		// Verify data content
		for i := 0; i < 100; i++ {
			assert.Equal(t, byte(i%256), chunk.Data[i])
		}
	default:
		t.Fatal("Expected chunk in queue")
	}

	assert.Equal(t, 1, rangeRequests)
}

func TestWriteChunksToFile(t *testing.T) {
	tempDir := t.TempDir()
	filePath := filepath.Join(tempDir, "test-write-chunks")

	file, err := os.Create(filePath)
	require.NoError(t, err)
	defer file.Close()

	ft := &DefaultFileTransfer{
		logger: observability.NewNoOpLogger(),
	}

	ctx := context.Background()
	chunkQueue := make(chan chunkData, 10)

	// Create test chunks (out of order to test seeking)
	chunks := []chunkData{
		{Offset: 100, Data: []byte("chunk2")},
		{Offset: 0, Data: []byte("chunk1")},
		{Offset: 200, Data: []byte("chunk3")},
	}

	// Start writer in background
	done := make(chan error)
	go func() {
		done <- ft.writeChunksToFile(ctx, file, chunkQueue, &DefaultDownloadTask{Size: 206})
	}()

	// Send chunks
	for _, chunk := range chunks {
		chunkQueue <- chunk
	}
	close(chunkQueue)

	// Wait for writer to finish
	err = <-done
	require.NoError(t, err)

	// Verify file content
	file.Close()
	content, err := os.ReadFile(filePath)
	require.NoError(t, err)

	// File should be sparse with data at correct offsets
	assert.Equal(t, "chunk1", string(content[0:6]))
	assert.Equal(t, "chunk2", string(content[100:106]))
	assert.Equal(t, "chunk3", string(content[200:206]))
}