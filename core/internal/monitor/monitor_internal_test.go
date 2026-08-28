package monitor

import (
	"context"
	"testing"
	"time"

	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type recordingResource struct {
	sampled chan struct{}
}

func (r *recordingResource) Sample() (*spb.StatsRecord, error) {
	select {
	case r.sampled <- struct{}{}:
	default:
	}
	return nil, nil
}

func (*recordingResource) Probe(context.Context) *spb.EnvironmentRecord {
	return nil
}

func TestSystemMonitorSamplesImmediately(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	sm := &SystemMonitor{
		ctx:              ctx,
		samplingInterval: time.Hour,
		logger:           observability.NewNoOpLogger(),
	}
	sm.state.Store(StateRunning)

	resource := &recordingResource{sampled: make(chan struct{}, 1)}
	done := make(chan struct{})
	go func() {
		sm.monitorResource(resource)
		close(done)
	}()

	select {
	case <-resource.sampled:
	case <-time.After(time.Second):
		t.Fatal("monitor did not sample immediately")
	}

	cancel()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("monitor did not stop")
	}
}
