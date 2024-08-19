package filetransfer_test

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/pkg/observability"
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
		observability.NewNoOpLogger(),
		filetransfer.NewFileTransferStats(),
	)

	// Mocking task
	task := &filetransfer.DefaultDownloadTask{
		Path: "test-download-file.txt",
		Url:  mockServer.URL,
	}
	defer os.Remove(task.Path)

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
		observability.NewNoOpLogger(),
		filetransfer.NewFileTransferStats(),
	)

	// Creating a file to be uploaded
	filename := "test-upload-file.txt"
	err := os.WriteFile(filename, contentExpected, 0644)
	assert.NoError(t, err)
	defer os.Remove(filename)

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
		observability.NewNoOpLogger(),
		filetransfer.NewFileTransferStats(),
	)

	tempFile, err := os.CreateTemp("", "")
	assert.NoError(t, err)
	_, err = tempFile.Write(entireContent)
	assert.NoError(t, err)
	tempFile.Close()
	defer os.Remove(tempFile.Name())

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
		observability.NewNoOpLogger(),
		filetransfer.NewFileTransferStats(),
	)

	tempFile, err := os.CreateTemp("", "")
	assert.NoError(t, err)
	_, err = tempFile.Write(entireContent)
	assert.NoError(t, err)
	tempFile.Close()
	defer os.Remove(tempFile.Name())

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
	err := uploadToServerWithHandler(t, fnfHandler)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "404")
	// 404s shouldn't be retried.
	assert.NotContains(t, err.Error(), "giving up after 2 attempt(s)")
}

func TestDefaultFileTransfer_UploadConnectionClosed(t *testing.T) {
	closeHandler := func(w http.ResponseWriter, r *http.Request) {
		hj, ok := w.(http.Hijacker)
		assert.True(t, ok, "webserver doesn't support hijacking")
		conn, _, err := hj.Hijack()
		assert.NoError(t, err, "hijacking error")
		conn.Close()
	}
	err := uploadToServerWithHandler(t, closeHandler)
	assert.Error(t, err)
	assert.Condition(t, func() bool {
		return strings.Contains(err.Error(), "EOF") ||
			strings.Contains(err.Error(), "connection reset")
	})
	assert.Contains(t, err.Error(), "giving up after 2 attempt(s)")
}

func TestDefaultFileTransfer_UploadContextCancelled(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		cancel()
	}))
	ft := filetransfer.NewDefaultFileTransfer(
		impatientClient(),
		observability.NewNoOpLogger(),
		filetransfer.NewFileTransferStats(),
	)

	tempFile, err := os.CreateTemp("", "")
	assert.NoError(t, err)
	defer os.Remove(tempFile.Name())

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
		observability.NewNoOpLogger(),
		filetransfer.NewFileTransferStats(),
	)

	tempFile, err := os.CreateTemp("", "")
	assert.NoError(t, err)
	defer os.Remove(tempFile.Name())

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

func uploadToServerWithHandler(
	t *testing.T,
	handler func(w http.ResponseWriter, r *http.Request),
) error {
	server := httptest.NewServer(http.HandlerFunc(handler))
	defer server.Close()
	ft := filetransfer.NewDefaultFileTransfer(
		impatientClient(),
		observability.NewNoOpLogger(),
		filetransfer.NewFileTransferStats(),
	)

	tempFile, err := os.CreateTemp("", "")
	assert.NoError(t, err)
	defer os.Remove(tempFile.Name())

	task := &filetransfer.DefaultUploadTask{
		Path: tempFile.Name(),
		Url:  server.URL,
	}

	return ft.Upload(task)
}

func impatientClient() *retryablehttp.Client {
	client := retryablehttp.NewClient()
	client.RetryMax = 1
	client.RetryWaitMin = 1 * time.Millisecond
	return client
}
