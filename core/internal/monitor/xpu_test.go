package monitor

import (
	"context"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// unresponsiveClient mimics a sidecar that is wedged in a device query and
// never answers, like a real gRPC client returning only once the caller's
// context is done.
type unresponsiveClient struct {
	spb.SystemMonitorServiceClient
}

func (c *unresponsiveClient) GetStats(
	ctx context.Context,
	_ *spb.GetStatsRequest,
	_ ...grpc.CallOption,
) (*spb.GetStatsResponse, error) {
	<-ctx.Done()
	return nil, status.FromContextError(ctx.Err()).Err()
}

func TestXPUSampleUnresponsiveSidecar(t *testing.T) {
	xpu := &XPU{
		client:        &unresponsiveClient{},
		sampleTimeout: 50 * time.Millisecond,
	}

	sampled := make(chan error, 1)
	go func() {
		_, err := xpu.Sample()
		sampled <- err
	}()

	select {
	case err := <-sampled:
		require.Error(t, err)
		require.Equal(t, codes.DeadlineExceeded, status.Code(err))
	case <-time.After(10 * time.Second):
		t.Fatal("Sample did not return while the sidecar was unresponsive")
	}
}
