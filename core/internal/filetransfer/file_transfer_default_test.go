package filetransfer_test

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/observabilitytest"
)

func TestDefaultFileTransfer_Download(t *testing.T) {
	// Content to be downloaded
	contentExpected := []byte("test content for download")

	// Creating a mock HTTP server
	mockServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {

		// add body to the response
		_, err := w.Write(contentExpected)
		assert.NoError(t, err)

		// Assertions
		// Compare the method
		assert.Equal(t, r.Method, http.MethodGet)
	}))
	defer mockServer.Close()

	// Creating a file transfer
	ft := filetransfer.NewDefaultFileTransfer(
		retryablehttp.NewClient(),
		observabilitytest.NewTestLogger(t),
		filetransfer.NewFileTransferStats(),
	)

	// Mocking task
	task := &filetransfer.DefaultDownloadTask{
		Path: "test-download-file.txt",
		Url:  mockServer.URL,
	}
	defer func() {
		_ = os.Remove(task.Path)
	}()

	// Performing the download
	err := ft.Download(task)
	assert.NoError(t, err)

	// Read the downloaded file
	content, err := os.ReadFile(task.Path)
	assert.NoError(t, err)
	assert.Equal(t, contentExpected, content)
	assert.Equal(t, task.Response.StatusCode, http.StatusOK)
}

func TestDefaultFileTransfer_Upload(t *testing.T) {
	// Content to be uploaded
	contentExpected := []byte("test content for upload")

	// Headers to be tested
	headers := []string{
		"X-Test-1:x:: test",
		"X-Test-2:",
		"X-Test-3",
		"X-Test-4: test",
	}

	// Creating a mock HTTP server
	mockServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {

		// Reading the body
		body, err := io.ReadAll(r.Body)
		assert.NoError(t, err)

		// Assertions

		// Compare the content
		assert.Equal(t, contentExpected, body)

		// Compare the method
		assert.Equal(t, r.Method, http.MethodPut)

		// Compare the headers
		assert.Equal(t, r.Header.Get("X-Test-1"), "x:: test")
		assert.Equal(t, r.Header.Get("X-Test-2"), "")
		assert.Equal(t, r.Header.Get("X-Test-3"), "")
		assert.Equal(t, r.Header.Get("X-Test-4"), "test")
	}))
	defer mockServer.Close()

	// Creating a file transfer
	ft := filetransfer.NewDefaultFileTransfer(
		retryablehttp.NewClient(),
		observabilitytest.NewTestLogger(t),
		filetransfer.NewFileTransferStats(),
	)

	// Creating a file to be uploaded
	filename := "test-upload-file.txt"
	err := os.WriteFile(filename, contentExpected, 0644)
	assert.NoError(t, err)
	defer func() {
		_ = os.Remove(filename)
	}()

	// Mocking task
	task := &filetransfer.DefaultUploadTask{
		Path:    filename,
		Url:     mockServer.URL,
		Headers: headers,
	}

	// Performing the upload
	err = ft.Upload(task)
	assert.NoError(t, err)
	assert.Equal(t, task.Response.StatusCode, http.StatusOK)
}

func TestDefaultFileTransfer_UploadOffsetChunk(t *testing.T) {
	entireContent := []byte("test content for upload")
	expectedContent := []byte("content")

	chunkCheckHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(r.Body)
		assert.NoError(t, err)
		assert.Equal(t, expectedContent, body)
	})
	server := httptest.NewServer(chunkCheckHandler)

	ft := filetransfer.NewDefaultFileTransfer(
		impatientClient(),
		observabilitytest.NewTestLogger(t),
		filetransfer.NewFileTransferStats(),
	)

	tempFile, err := os.CreateTemp("", "")
	assert.NoError(t, err)
	_, err = tempFile.Write(entireContent)
	assert.NoError(t, err)
	_ = tempFile.Close()
	defer func() {
		_ = os.Remove(tempFile.Name())
	}()

	task := &filetransfer.DefaultUploadTask{
		Path:   tempFile.Name(),
		Url:    server.URL,
		Offset: 5,
		Size:   7,
	}

	err = ft.Upload(task)
	assert.NoError(t, err)
}

func TestDefaultFileTransfer_UploadOffsetChunkOverlong(t *testing.T) {
	entireContent := []byte("test content for upload")

	chunkCheckHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
	})
	server := httptest.NewServer(chunkCheckHandler)

	ft := filetransfer.NewDefaultFileTransfer(
		impatientClient(),
		observabilitytest.NewTestLogger(t),
		filetransfer.NewFileTransferStats(),
	)

	tempFile, err := os.CreateTemp("", "")
	assert.NoError(t, err)
	_, err = tempFile.Write(entireContent)
	assert.NoError(t, err)
	_ = tempFile.Close()
	defer func() {
		_ = os.Remove(tempFile.Name())
	}()

	task := &filetransfer.DefaultUploadTask{
		Path:   tempFile.Name(),
		Url:    server.URL,
		Offset: 17,
		Size:   1000,
	}

	err = ft.Upload(task)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "offset + size exceeds the file size")
}

func TestDefaultFileTransfer_UploadNotFound(t *testing.T) {
	fnfHandler := func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}
	handlerCalled, err := uploadToServerWithCountedHandler(t, fnfHandler)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "404")
	// 404s shouldn't be retried.
	assert.Equal(t, 1, handlerCalled)
}

func TestDefaultFileTransfer_UploadErrorWithBody(t *testing.T) {
	errorBody := "detailed error message from server"
	errorHandler := func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte(errorBody))
	}
	handlerCalled, err := uploadToServerWithCountedHandler(t, errorHandler)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "400")
	assert.Contains(t, err.Error(), errorBody)
	// 400s shouldn't be retried.
	assert.Equal(t, 1, handlerCalled)
}

func TestDefaultFileTransfer_UploadErrorWithLargeBody(t *testing.T) {
	// Create an error body larger than 1024 bytes
	largeErrorBody := strings.Repeat("error message ", 100)
	errorHandler := func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte(largeErrorBody))
	}
	handlerCalled, err := uploadToServerWithCountedHandler(t, errorHandler)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "400")
	assert.Contains(t, err.Error(), "error message")
	// 100 bytes for the prefix in the error
	assert.Less(t, len(err.Error()), 1024+100)
	// 400s shouldn't be retried.
	assert.Equal(t, 1, handlerCalled)
}

func TestDefaultFileTransfer_UploadErrorWithUnreadableBody(t *testing.T) {
	errorHandler := func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Length", "100")
		w.WriteHeader(http.StatusBadRequest)
		// Close connection without sending body to simulate read error
		hj, ok := w.(http.Hijacker)
		if ok {
			conn, _, err := hj.Hijack()
			if err == nil {
				_ = conn.Close()
			}
		}
	}
	handlerCalled, err := uploadToServerWithCountedHandler(t, errorHandler)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "400")
	assert.Contains(t, err.Error(), "error reading body")
	// 400s shouldn't be retried.
	assert.Equal(t, 1, handlerCalled)
}

func TestDefaultFileTransfer_UploadConnectionClosed(t *testing.T) {
	closeHandler := func(w http.ResponseWriter, r *http.Request) {
		hj, ok := w.(http.Hijacker)
		assert.True(t, ok, "webserver doesn't support hijacking")
		conn, _, err := hj.Hijack()
		assert.NoError(t, err, "hijacking error")
		_ = conn.Close()
	}
	handlerCalled, err := uploadToServerWithCountedHandler(t, closeHandler)
	assert.Error(t, err)
	assert.Condition(t, func() bool {
		return strings.Contains(err.Error(), "EOF") ||
			strings.Contains(err.Error(), "connection reset")
	})
	assert.Equal(t, 2, handlerCalled)
}

func TestDefaultFileTransfer_UploadContextCancelled(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		cancel()
	}))
	ft := filetransfer.NewDefaultFileTransfer(
		impatientClient(),
		observabilitytest.NewTestLogger(t),
		filetransfer.NewFileTransferStats(),
	)

	tempFile, err := os.CreateTemp("", "")
	assert.NoError(t, err)
	defer func() {
		_ = os.Remove(tempFile.Name())
	}()

	err = ft.Upload(&filetransfer.DefaultUploadTask{
		Path:    tempFile.Name(),
		Url:     server.URL,
		Context: ctx,
	})

	assert.Error(t, err)
	assert.Contains(t, err.Error(), "context canceled")
	// Context cancellation shouldn't result in a retry.
	assert.NotContains(t, err.Error(), "giving up after 2 attempt(s)")
}

func TestDefaultFileTransfer_UploadNoServer(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	ft := filetransfer.NewDefaultFileTransfer(
		impatientClient(),
		observabilitytest.NewTestLogger(t),
		filetransfer.NewFileTransferStats(),
	)

	tempFile, err := os.CreateTemp("", "")
	assert.NoError(t, err)
	defer func() {
		_ = os.Remove(tempFile.Name())
	}()

	task := &filetransfer.DefaultUploadTask{
		Path: tempFile.Name(),
		Url:  server.URL,
	}

	// Close the server before the upload begins.
	server.Close()

	err = ft.Upload(task)
	assert.Error(t, err)
	assert.Nil(t, task.Response)
	assert.Contains(t, err.Error(), "connection refused")
	assert.Contains(t, err.Error(), "giving up after 2 attempt(s)")
}

// Start test server and count number of times the handler was called
func uploadToServerWithCountedHandler(
	t *testing.T,
	handler func(w http.ResponseWriter, r *http.Request),
) (int, error) {
	handlerCalled := int64(0)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt64(&handlerCalled, 1)
		handler(w, r)
	}))
	defer server.Close()
	ft := filetransfer.NewDefaultFileTransfer(
		impatientClient(),
		observabilitytest.NewTestLogger(t),
		filetransfer.NewFileTransferStats(),
	)

	tempFile, err := os.CreateTemp("", "")
	assert.NoError(t, err)
	defer func() {
		_ = os.Remove(tempFile.Name())
	}()

	task := &filetransfer.DefaultUploadTask{
		Path: tempFile.Name(),
		Url:  server.URL,
	}

	err = ft.Upload(task)
	return int(atomic.LoadInt64(&handlerCalled)), err
}

func impatientClient() *retryablehttp.Client {
	client := retryablehttp.NewClient()
	client.RetryMax = 1
	client.RetryWaitMin = 1 * time.Millisecond
	return client
}

func TestDefaultFileTransfer_DownloadMultipart(t *testing.T) {
	// Create a test file to serveFile
	contentSize := int64(5*1024*1024 + 100) // 5MB + 100 bytes
	partSize := int64(2 * 1024 * 1024)      // 2MB
	sourcePath, content := createSourceFile(t, contentSize)
	defer os.Remove(sourcePath)

	server := httptest.NewServer(http.FileServer(http.Dir(filepath.Dir(sourcePath))))
	defer server.Close()

	ft := filetransfer.NewTestDefaultFileTransfer(contentSize, partSize)
	downloadedPath := createDownloadFile(t)
	defer os.Remove(downloadedPath)

	task := &filetransfer.DefaultDownloadTask{
		Path:    downloadedPath,
		Url:     server.URL + "/" + filepath.Base(sourcePath),
		Size:    contentSize,
		Context: context.Background(),
	}
	err := ft.Download(task)
	require.NoError(t, err)
	verifyFileContent(t, downloadedPath, content)
}

func TestDefaultFileTransfer_DownloadMultipartCancelContext(t *testing.T) {
	// No need to create the source file since the server
	// cancel the context directly without serving anything.
	ctx, cancel := context.WithCancel(context.Background())
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		cancel()
	}))
	defer server.Close()
	contentSize := int64(5*1024*1024 + 100) // 5MB + 100 bytes
	chunkSize := int64(2 * 1024 * 1024)

	downloadedPath := createDownloadFile(t)
	defer os.Remove(downloadedPath)

	ft := filetransfer.NewTestDefaultFileTransfer(contentSize, chunkSize)
	task := &filetransfer.DefaultDownloadTask{
		Path:    downloadedPath,
		Url:     server.URL,
		Size:    contentSize,
		Context: ctx,
	}
	err := ft.Download(task)
	require.Error(t, err)
	require.ErrorIs(t, err, context.Canceled)
}

type errorFileWriter struct {
	failAtOffset int64
}

func (e *errorFileWriter) WriteAt(p []byte, off int64) (n int, err error) {
	if off == e.failAtOffset {
		return 0, fmt.Errorf("injected file write error at offset %d", off)
	}
	return len(p), nil
}

func TestDefaultFileTransfer_DownloadMultipartFileWriteError(t *testing.T) {
	// Create a test file to serveFile
	contentSize := int64(5*1024*1024 + 100) // 5MB + 100 bytes
	partSize := int64(2 * 1024 * 1024)      // 2MB
	sourcePath, _ := createSourceFile(t, contentSize)
	defer os.Remove(sourcePath)

	server := httptest.NewServer(http.FileServer(http.Dir(filepath.Dir(sourcePath))))
	defer server.Close()
	url := server.URL + "/" + filepath.Base(sourcePath)
	ft := filetransfer.NewTestDefaultFileTransfer(contentSize, partSize)
	task := &filetransfer.DefaultDownloadTask{
		Path:    "doesn't matter, we use mock file",
		Url:     url,
		Size:    contentSize,
		Context: context.Background(),
	}

	downloadedFile := errorFileWriter{failAtOffset: partSize}
	err := ft.DownloadMultipart(task, &downloadedFile)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "injected file write error at offset")
}

// Helper functions for multipart download tests

func createSourceFile(t *testing.T, contentSize int64) (string, []byte) {
	sourceFile, err := os.CreateTemp("", "test-multipart-source-*.bin")
	require.NoError(t, err)
	sourcePath := sourceFile.Name()
	content := generateTestContent(contentSize)
	_, err = sourceFile.Write(content)
	require.NoError(t, err)
	require.NoError(t, sourceFile.Close())
	return sourcePath, content
}

func createDownloadFile(t *testing.T) string {
	downloadFile, err := os.CreateTemp("", "test-multipart-downloaded-*.bin")
	require.NoError(t, err)
	downloadPath := downloadFile.Name()
	downloadFile.Close()
	return downloadPath
}

// generateTestContent creates a file with fixed pattern.
// we don't need random content for the test.
func generateTestContent(size int64) []byte {
	content := make([]byte, size)
	pattern := []byte("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
	for i := int64(0); i < size; i++ {
		content[i] = pattern[i%int64(len(pattern))]
	}
	return content
}

// verifyFileContent checks if downloaded file matches expected content
func verifyFileContent(t *testing.T, filePath string, expectedContent []byte) {
	actualContent, err := os.ReadFile(filePath)
	require.NoError(t, err)
	assert.Equal(t, expectedContent, actualContent, "File content mismatch")
}
