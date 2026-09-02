package parquet_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet"
)

func TestDownloadRunHistoryFile_TruncatedBodyLeavesNoFile(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Length", "100")
			_, _ = w.Write([]byte("partial"))
		}))
	defer server.Close()
	dir := t.TempDir()

	err := parquet.DownloadRunHistoryFile(
		context.Background(),
		api.NewClient(api.ClientOptions{NonRetryTimeout: time.Minute}),
		server.URL,
		filepath.Join(dir, "test.runhistory.parquet"),
	)

	require.Error(t, err)
	entries, err := os.ReadDir(dir)
	require.NoError(t, err)
	require.Empty(t, entries, "no partial or temp file left behind")
}
