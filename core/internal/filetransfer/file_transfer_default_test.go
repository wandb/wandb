package filetransfer_test

import (
	"io"
	"math/rand"
	"net/http"
	"net/http/httptest"
	"os"
	"sync/atomic"
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
	ft := filetransfer.NewDefaultFileTransfer(observability.NewNoOpLogger(), retryablehttp.NewClient())

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
	ft := filetransfer.NewDefaultFileTransfer(observability.NewNoOpLogger(), retryablehttp.NewClient())

	// Creating a file to be uploaded
	filename := "test-upload-file.txt"
	err := os.WriteFile(filename, contentExpected, 0644)
	assert.NoError(t, err)
	defer os.Remove(filename)

	// Mocking task
	task := &filetransfer.Task{
		Type:    filetransfer.UploadTask,
		Path:    filename,
		Url:     mockServer.URL,
		Headers: headers,
	}

	// Performing the upload
	err = ft.Upload(task)
	assert.NoError(t, err)
}

func TestManagedDefaultFileTransfer_FaultyUpload(t *testing.T) {
	// Create 1000 temporary files for testing
	tempDir, err := os.MkdirTemp("", "test-files")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(tempDir)

	var filePaths []string
	for i := 0; i < 1000; i++ {
		tempFile, err := os.CreateTemp(tempDir, "test-file-*")
		if err != nil {
			t.Fatal(err)
		}
		filePaths = append(filePaths, tempFile.Name())
	}

	// Create a channel to let the server signal that it should be closed
	closeServer := make(chan bool)

	// Create a test server that fails 5% of the time and shuts down after 100 responses
	var responsesServed int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if atomic.AddInt32(&responsesServed, 1) > 100 {
            select {
			case closeServer <- true:
			default:
			}
            return
        }

		if rand.Float64() < 0.05 {
			// Simulate various errors
			errorScenarios := []func(){
				func() { w.WriteHeader(http.StatusNotFound) }, // 404 Not Found
				func() {
					hj, ok := w.(http.Hijacker)
					if !ok {
						t.Error("webserver doesn't support hijacking")
					}
					conn, _, err := hj.Hijack()
					if err != nil {
						t.Errorf("hijacking error: %v", err)
					}
					conn.Close()
				}, // Closed connection
				func() {}, // Non-response
			}
			scenario := errorScenarios[rand.Intn(len(errorScenarios))]
			scenario()
		} else {
			w.WriteHeader(http.StatusOK)
		}
	}))
	defer server.Close()

	// Listen for the close signal and terminate the server early.
	go func() {
		<-closeServer
		server.Close()
	}()

	ft := filetransfer.NewDefaultFileTransfer(observability.NewNoOpLogger(), retryablehttp.NewClient())
	ftm := filetransfer.NewFileTransferManager(
		filetransfer.WithLogger(observability.NewNoOpLogger()),
		filetransfer.WithFileTransfer(ft),
	)
	ftm.Start()

	// Count successful uploads
	var successfulUploads int32

	// Upload all the files concurrently
	for _, filePath := range filePaths {
		ftm.AddTask(&filetransfer.Task{
			Path: filePath,
			Url:  server.URL,
			CompletionCallback: func(task *filetransfer.Task) {
				if task.Err == nil {
					atomic.AddInt32(&successfulUploads, 1)
				}
			},
		})
	}

	// Wait for all uploads to complete
	ftm.Close()

	// It should be impossible for it to succeed more than 100 times,
	// and less than a 1 / 10**7 chance it doesn't succeed at least 80 times.
	if successfulUploads < 80 || successfulUploads > 100 {
		t.Errorf("expected 80-100 successful uploads, got %d", successfulUploads)
	}
}
