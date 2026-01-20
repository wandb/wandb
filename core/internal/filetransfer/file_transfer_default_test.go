package filetransfer_test

import (
	"bytes"
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/observabilitytest"
)

// newFileTransfer returns a new DefaultFileTransfer for tests that uses
// a non-retrying HTTP client.
func newFileTransfer(t *testing.T) *filetransfer.DefaultFileTransfer {
	t.Helper()

	client := retryablehttp.NewClient()
	client.RetryMax = 0

	return filetransfer.NewDefaultFileTransfer(
		client,
		observabilitytest.NewTestLogger(t),
		filetransfer.NewFileTransferStats(),
	)
}

// runServer starts a server for the duration of the test running the given
// handler function.
//
// Returns the server's URL.
func runServer(
	t *testing.T,
	handler func(w http.ResponseWriter, r *http.Request),
) string {
	t.Helper()

	server := httptest.NewServer(http.HandlerFunc(handler))
	t.Cleanup(server.Close)

	return server.URL
}

// writeTempFile creates a temporary file with the given contents and returns
// its path.
func writeTempFile(t *testing.T, content []byte) string {
	t.Helper()

	path := filepath.Join(t.TempDir(), "test-data.txt")
	err := os.WriteFile(path, content, 0o644)
	require.NoError(t, err)

	return path
}

func TestDefaultFileTransfer_Download(t *testing.T) {
	path := filepath.Join(t.TempDir(), "test-file.txt")
	contentExpected := []byte("test content for download")
	testURL := runServer(t, func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, r.Method, http.MethodGet)

		_, err := w.Write(contentExpected)
		assert.NoError(t, err)
	})

	task := &filetransfer.DefaultDownloadTask{
		Path: path,
		Url:  testURL,
	}
	err := newFileTransfer(t).Download(task)

	require.NoError(t, err)

	content, err := os.ReadFile(path)
	assert.NoError(t, err)
	assert.Equal(t, contentExpected, content)
	assert.Equal(t, task.Response.StatusCode, http.StatusOK)
}

func TestDefaultFileTransfer_Upload(t *testing.T) {
	expectedContent := []byte("test content for upload")
	path := writeTempFile(t, expectedContent)
	expectedHeaders := []string{
		"X-Test-1:x:: test",
		"X-Test-2:",
		"X-Test-3",
		"X-Test-4: test",
	}
	testURL := runServer(t, func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(r.Body)
		require.NoError(t, err)

		assert.Equal(t, expectedContent, body)
		assert.Equal(t, r.Method, http.MethodPut)
		assert.Equal(t, r.Header.Get("X-Test-1"), "x:: test")
		assert.Equal(t, r.Header.Get("X-Test-2"), "")
		assert.Equal(t, r.Header.Get("X-Test-3"), "")
		assert.Equal(t, r.Header.Get("X-Test-4"), "test")
	})

	task := &filetransfer.DefaultUploadTask{
		Path:    path,
		Url:     testURL,
		Headers: expectedHeaders,
	}
	err := newFileTransfer(t).Upload(task)

	assert.NoError(t, err)
	assert.Equal(t, task.Response.StatusCode, http.StatusOK)
}

func TestDefaultFileTransfer_UploadOffsetChunk(t *testing.T) {
	path := writeTempFile(t, []byte("test content for upload"))
	expectedContent := []byte("content")
	testURL := runServer(t, func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(r.Body)
		assert.NoError(t, err)
		assert.Equal(t, expectedContent, body)
	})

	err := newFileTransfer(t).Upload(&filetransfer.DefaultUploadTask{
		Path:   path,
		Url:    testURL,
		Offset: 5,
		Size:   7,
	})

	assert.NoError(t, err)
}

func TestDefaultFileTransfer_UploadOffsetChunkOverlong(t *testing.T) {
	path := writeTempFile(t, []byte("test content for upload"))
	testURL := runServer(t, func(w http.ResponseWriter, r *http.Request) {})

	err := newFileTransfer(t).Upload(&filetransfer.DefaultUploadTask{
		Path:   path,
		Url:    testURL,
		Offset: 17,
		Size:   1000,
	})

	assert.ErrorContains(t, err, "offset + size exceeds the file size")
}

func TestDefaultFileTransfer_UploadNotFound(t *testing.T) {
	path := writeTempFile(t, []byte("test data"))
	testURL := runServer(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	})

	err := newFileTransfer(t).Upload(&filetransfer.DefaultUploadTask{
		Path: path,
		Url:  testURL,
	})

	assert.ErrorContains(t, err, "404")
}

func TestDefaultFileTransfer_UploadErrorWithBody(t *testing.T) {
	path := writeTempFile(t, []byte("test data"))
	errorBody := "detailed error message from server"
	testURL := runServer(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte(errorBody))
	})

	err := newFileTransfer(t).Upload(&filetransfer.DefaultUploadTask{
		Path: path,
		Url:  testURL,
	})

	assert.ErrorContains(t, err, "400")
	assert.ErrorContains(t, err, errorBody)
}

func TestDefaultFileTransfer_UploadErrorWithLargeBody(t *testing.T) {
	path := writeTempFile(t, []byte("test data"))
	largeErrorBody := strings.Repeat("error message ", 100)
	testURL := runServer(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte(largeErrorBody))
	})

	err := newFileTransfer(t).Upload(&filetransfer.DefaultUploadTask{
		Path: path,
		Url:  testURL,
	})

	assert.ErrorContains(t, err, "400")
	assert.ErrorContains(t, err, "error message")
	// 100 bytes for the prefix in the error
	assert.Less(t, len(err.Error()), 1024+100)
}

func TestDefaultFileTransfer_UploadErrorWithUnreadableBody(t *testing.T) {
	path := writeTempFile(t, []byte("test data"))
	testURL := runServer(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Length", "100")
		w.WriteHeader(http.StatusBadRequest)
		// Close connection without sending body to simulate read error
		hj, ok := w.(http.Hijacker)
		require.True(t, ok, "webserver doesn't support hijacking")

		conn, _, err := hj.Hijack()
		require.NoError(t, err, "hijacking error")

		_ = conn.Close()
	})

	err := newFileTransfer(t).Upload(&filetransfer.DefaultUploadTask{
		Path: path,
		Url:  testURL,
	})

	assert.Error(t, err)
	assert.Contains(t, err.Error(), "400")
	assert.Contains(t, err.Error(), "error reading body")
}

func TestDefaultFileTransfer_UploadConnectionClosed(t *testing.T) {
	path := writeTempFile(t, []byte("test data"))
	testURL := runServer(t, func(w http.ResponseWriter, r *http.Request) {
		hj, ok := w.(http.Hijacker)
		require.True(t, ok, "webserver doesn't support hijacking")

		conn, _, err := hj.Hijack()
		require.NoError(t, err, "hijacking error")

		_ = conn.Close()
	})

	err := newFileTransfer(t).Upload(&filetransfer.DefaultUploadTask{
		Path: path,
		Url:  testURL,
	})

	// Can be "EOF", "use of closed network connection" or others.
	assert.Error(t, err)
}

func TestDefaultFileTransfer_UploadContextCancelled(t *testing.T) {
	path := writeTempFile(t, []byte("test data"))
	ctx, cancel := context.WithCancel(context.Background())
	testURL := runServer(t, func(w http.ResponseWriter, r *http.Request) {
		cancel()
	})

	err := newFileTransfer(t).Upload(&filetransfer.DefaultUploadTask{
		Path:    path,
		Url:     testURL,
		Context: ctx,
	})

	assert.Error(t, err)
	assert.Contains(t, err.Error(), "context canceled")
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
