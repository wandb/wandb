package server

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/wrapperspb"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// telemetryExportInterval is how often a telemetry proxy exports metrics.
const telemetryExportInterval = 500 * time.Millisecond

func apiTelemetryProxyCount(nc *Connection) int {
	nc.apiTelemetryMu.Lock()
	defer nc.apiTelemetryMu.Unlock()
	return len(nc.apiTelemetryProxies)
}

func TestHandleApiCleanupShutsDownTelemetry(t *testing.T) {
	var exports atomic.Int64
	backend := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			exports.Add(1)
			w.WriteHeader(http.StatusOK)
		}))
	t.Cleanup(backend.Close)

	serverConn, clientConn := net.Pipe()
	t.Cleanup(func() { _ = serverConn.Close() })
	t.Cleanup(func() { _ = clientConn.Close() })

	nc := NewConnection(
		context.Background(),
		func() {},
		ConnectionParams{
			ID:   "test",
			Conn: serverConn,
		},
	)

	nc.handleApiInit("init", &spb.ServerApiInitRequest{
		Settings: &spb.Settings{
			BaseUrl: wrapperspb.String(backend.URL),
			ApiKey:  wrapperspb.String("test-api-key"),
		},
	})

	apiID := (<-nc.outChan).GetApiInitResponse().GetApiId()
	require.NotEmpty(t, apiID, "expected an API instance to be created")
	require.Equal(t, 1, apiTelemetryProxyCount(nc))
	require.Eventually(t,
		func() bool { return exports.Load() > 0 },
		10*time.Second, 10*time.Millisecond,
		"expected the telemetry proxy to export to the backend")

	nc.handleApiCleanup("cleanup", &spb.ServerApiCleanupRequest{ApiId: apiID})

	assert.Zero(t, apiTelemetryProxyCount(nc))
	assert.Eventually(t,
		func() bool {
			before := exports.Load()
			time.Sleep(3 * telemetryExportInterval)
			return exports.Load() == before
		},
		15*time.Second, telemetryExportInterval,
		"expected telemetry exports to stop after cleanup")
}
