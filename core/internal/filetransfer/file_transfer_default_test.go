package filetransfer_test

import (
	"bytes"
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
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
	ft := newFileTransfer(t, nil, nil)

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
	ft := newFileTransfer(t, nil, nil)

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

	ft := newFileTransfer(t, impatientClient(), nil)

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

	ft := newFileTransfer(t, impatientClient(), nil)

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
	ft := newFileTransfer(t, impatientClient(), nil)

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
	ft := newFileTransfer(t, impatientClient(), nil)

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

func TestProgressReader_TracksProgress(t *testing.T) {
	var lastProcessed, lastTotal int64
	callback := func(processed, total int64) {
		lastProcessed = processed
		lastTotal = total
	}
	data := bytes.NewReader([]byte("some data"))
	progressReader := filetransfer.NewProgressReader(
		data,
		int64(data.Len()),
		callback,
	)

	_, err := progressReader.Read(make([]byte, 2))
	assert.NoError(t, err)
	assert.EqualValues(t, 2, lastProcessed)
	assert.EqualValues(t, 9, lastTotal)

	_, err = progressReader.Seek(2, io.SeekCurrent)
	assert.NoError(t, err)
	assert.EqualValues(t, 4, lastProcessed)
	assert.EqualValues(t, 9, lastTotal)

	_, err = progressReader.Seek(0, io.SeekStart)
	assert.NoError(t, err)
	assert.EqualValues(t, 0, lastProcessed)
	assert.EqualValues(t, 9, lastTotal)
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
	ft := newFileTransfer(t, impatientClient(), nil)

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

// newFileTransfer creates a new DefaultFileTransfer with optional
// custom client and extra headers
func newFileTransfer(
	t *testing.T,
	client *retryablehttp.Client,
	extraHeaders map[string]string,
) *filetransfer.DefaultFileTransfer {
	if client == nil {
		client = retryablehttp.NewClient()
	}
	return filetransfer.NewDefaultFileTransfer(
		client,
		observabilitytest.NewTestLogger(t),
		filetransfer.NewFileTransferStats(),
		extraHeaders,
	)
}

// newFileTransferWithExtraHeaders creates a new DefaultFileTransfer
// with the provided extra headers
func newFileTransferWithExtraHeaders(
	t *testing.T,
	extraHeaders map[string]string,
) *filetransfer.DefaultFileTransfer {
	return newFileTransfer(t, nil, extraHeaders)
}

// verifyHeadersInRequest verifies that the HTTP request contains
// the expected headers.
// We use r.Header.Get(key) instead of assert.EqualValues() because:
// - r.Header is of type http.Header (map[string][]string)
// - expectedHeaders is of type map[string]string
func verifyHeadersInRequest(
	t *testing.T,
	r *http.Request,
	expectedHeaders map[string]string,
) {
	// Mark as helper to show the caller's location when assert fails
	// inside a helper function.
	t.Helper()
	for key, expectedValue := range expectedHeaders {
		assert.Equal(
			t,
			expectedValue,
			r.Header.Get(key),
			"Header %s should have value %s",
			key,
			expectedValue,
		)
	}
}

func TestDefaultFileTransfer_DownloadWithExtraHeaders(t *testing.T) {
	contentExpected := []byte("test content for download")
	extraHeaders := map[string]string{
		"X-Custom-Header-1": "value1",
		"X-Custom-Header-2": "value2",
	}

	// Creating a mock HTTP server
	mockServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, err := w.Write(contentExpected)
		assert.NoError(t, err)

		assert.Equal(t, http.MethodGet, r.Method)
		verifyHeadersInRequest(t, r, extraHeaders)
	}))
	defer mockServer.Close()

	ft := newFileTransferWithExtraHeaders(t, extraHeaders)

	task := &filetransfer.DefaultDownloadTask{
		Path: "test-download-file-with-headers.txt",
		Url:  mockServer.URL,
	}
	defer func() {
		_ = os.Remove(task.Path)
	}()

	err := ft.Download(task)
	require.NoError(t, err)

	content, err := os.ReadFile(task.Path)
	require.NoError(t, err)
	assert.Equal(t, contentExpected, content)
	assert.Equal(t, http.StatusOK, task.Response.StatusCode)
}

func TestDefaultFileTransfer_UploadWithExtraHeaders(t *testing.T) {
	contentExpected := []byte("test content for upload")
	extraHeaders := map[string]string{
		"X-Custom-Upload-1": "upload-value1",
		"X-Custom-Upload-2": "upload-value2",
	}

	// Creating a mock HTTP server
	mockServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(r.Body)
		assert.NoError(t, err)
		assert.Equal(t, contentExpected, body)

		assert.Equal(t, http.MethodPut, r.Method)
		verifyHeadersInRequest(t, r, extraHeaders)
	}))
	defer mockServer.Close()

	ft := newFileTransferWithExtraHeaders(t, extraHeaders)

	filename := "test-upload-file-with-headers.txt"
	err := os.WriteFile(filename, contentExpected, 0644)
	require.NoError(t, err)
	defer func() {
		_ = os.Remove(filename)
	}()

	task := &filetransfer.DefaultUploadTask{
		Path: filename,
		Url:  mockServer.URL,
	}

	err = ft.Upload(task)
	require.NoError(t, err)
	assert.Equal(t, http.StatusOK, task.Response.StatusCode)
}
