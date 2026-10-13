package platform_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/provenance/platform"
)

func TestMetadataTimeoutRemainsAnExplicitGap(t *testing.T) {
	server := httptest.NewServer(
		http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { <-r.Context().Done() }),
	)
	defer server.Close()
	adapter := platform.NewGCP(
		platform.Config{SysRoot: t.TempDir(), Client: server.Client(), MetadataURL: server.URL},
	)
	started := time.Now()
	snapshot := adapter.Collect(context.Background(), 0)
	assert.Less(t, time.Since(started), 3*time.Second)
	assert.Equal(t, "timeout", snapshot.Capabilities["metadata_id"].Status)
	assert.Empty(t, snapshot.Identity.InstanceID)
	assert.Equal(t, "unknown", snapshot.Transport.Name)
}

func TestMalformedCounterIsAbsentInsteadOfZero(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "class", "net", "eth0", "statistics", "tx_bytes")
	require.NoError(t, os.MkdirAll(filepath.Dir(path), 0o700))
	require.NoError(t, os.WriteFile(path, []byte("not-a-number"), 0o600))
	snapshot := platform.NewLocal(platform.Config{SysRoot: root}).Collect(context.Background(), 0)
	assert.Empty(t, snapshot.Counters)
	assert.Equal(t, "malformed_counter", snapshot.Capabilities["network"].Reason)
}

func TestMetadataTimeoutIsRetried(t *testing.T) {
	var ready atomic.Bool
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !ready.Load() {
			<-r.Context().Done()
			return
		}
		_, _ = w.Write([]byte("projects/1/zones/us-central1-a"))
	}))
	defer server.Close()
	adapter := platform.NewGCP(
		platform.Config{
			SysRoot:     t.TempDir(),
			Client:      server.Client(),
			MetadataURL: server.URL,
			Labels:      map[string]string{},
		},
	)
	assert.Equal(
		t,
		"timeout",
		adapter.Collect(context.Background(), 0).Capabilities["metadata_zone"].Status,
	)
	ready.Store(true)
	snapshot := adapter.Collect(context.Background(), 0)
	assert.Equal(t, "us-central1-a", snapshot.Identity.Zone)
	assert.Equal(t, "available", snapshot.Capabilities["metadata_zone"].Status)
}
