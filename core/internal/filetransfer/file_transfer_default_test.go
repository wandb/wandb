package filetransfer_test

import (
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

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
	task := &filetransfer.Task{
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
	task := &filetransfer.Task{
		Path:    filename,
		Url:     mockServer.URL,
		Headers: headers,
	}

	// Performing the upload
	err = ft.Upload(task)
	assert.NoError(t, err)
}
