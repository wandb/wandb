package parquet_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet"
)

func testClient(nonRetryTimeout time.Duration) api.RetryableClient {
	return api.NewClient(api.ClientOptions{
		RetryMax:        0,
		RetryWaitMin:    time.Millisecond,
		RetryWaitMax:    time.Millisecond,
		NonRetryTimeout: nonRetryTimeout,
	})
}

// requireOnlyFiles asserts dir contains exactly the given file names,
// i.e. no leftover temp files.
func requireOnlyFiles(t *testing.T, dir string, names ...string) {
	t.Helper()

	entries, err := os.ReadDir(dir)
	require.NoError(t, err)

	actual := make([]string, 0, len(entries))
	for _, e := range entries {
		actual = append(actual, e.Name())
	}
	assert.ElementsMatch(t, names, actual)
}

func TestDownloadRunHistoryFile(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			_, _ = w.Write([]byte("parquet-bytes"))
		}))
	defer server.Close()
	dir := t.TempDir()
	filePath := filepath.Join(dir, "test.runhistory.parquet")

	err := parquet.DownloadRunHistoryFile(
		context.Background(),
		testClient(time.Minute),
		server.URL,
		filePath,
	)

	require.NoError(t, err)
	content, err := os.ReadFile(filePath)
	require.NoError(t, err)
	assert.Equal(t, "parquet-bytes", string(content))
	requireOnlyFiles(t, dir, "test.runhistory.parquet")
}

func TestDownloadRunHistoryFile_TruncatedBodyLeavesNoFile(t *testing.T) {
	// Declare more bytes than are sent so the client's body read fails.
	server := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Length", "100")
			_, _ = w.Write([]byte("partial"))
		}))
	defer server.Close()
	dir := t.TempDir()
	filePath := filepath.Join(dir, "test.runhistory.parquet")

	err := parquet.DownloadRunHistoryFile(
		context.Background(),
		testClient(time.Minute),
		server.URL,
		filePath,
	)

	require.Error(t, err)
	requireOnlyFiles(t, dir)
}

func TestDownloadRunHistoryFile_ClientTimeoutBoundsBodyRead(t *testing.T) {
	// The client's NonRetryTimeout becomes http.Client.Timeout, which keeps
	// running while the body streams; a body slower than the timeout must
	// fail without leaving a file behind.
	server := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			flusher := w.(http.Flusher)
			for range 50 {
				if _, err := w.Write([]byte("x")); err != nil {
					return
				}
				flusher.Flush()
				select {
				case <-r.Context().Done():
					return
				case <-time.After(20 * time.Millisecond):
				}
			}
		}))
	defer server.Close()
	dir := t.TempDir()
	filePath := filepath.Join(dir, "test.runhistory.parquet")

	err := parquet.DownloadRunHistoryFile(
		context.Background(),
		testClient(100*time.Millisecond),
		server.URL,
		filePath,
	)

	require.Error(t, err)
	requireOnlyFiles(t, dir)
}
