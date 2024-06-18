package filestream_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/waitingtest"
	"golang.org/x/time/rate"
)

func TestTransmitLoop_Sends(t *testing.T) {
	outputs := make(chan filestream.FsTransmitData)
	loop := filestream.TransmitLoop{
		TransmitRateLimit:  rate.NewLimiter(rate.Inf, 1),
		HeartbeatStopwatch: waitingtest.NewFakeStopwatch(),

		LogFatalAndStopWorking: func(err error) {},
		Send: func(
			ftd filestream.FsTransmitData,
			c chan<- map[string]any,
		) error {
			outputs <- ftd
			return nil
		},
	}
	testInput := filestream.FsTransmitData{Preempting: true}

	inputs := make(chan filestream.FsTransmitData)
	_ = loop.Start(inputs)
	inputs <- testInput
	close(inputs)

	select {
	case result := <-outputs:
		assert.Equal(t, testInput, result)
	case <-time.After(time.Second):
		t.Error("timeout after 1 second")
	}
}

func TestTransmitLoop_SendsHeartbeats(t *testing.T) {
	heartbeat := waitingtest.NewFakeStopwatch()
	inputs := make(chan filestream.FsTransmitData)
	defer close(inputs)
	outputs := make(chan filestream.FsTransmitData)
	loop := filestream.TransmitLoop{
		TransmitRateLimit:  rate.NewLimiter(rate.Inf, 1),
		HeartbeatStopwatch: heartbeat,

		LogFatalAndStopWorking: func(err error) {},
		Send: func(
			ftd filestream.FsTransmitData,
			c chan<- map[string]any,
		) error {
			outputs <- ftd
			return nil
		},
	}

	loop.Start(inputs)
	heartbeat.SetDone()

	select {
	case result := <-outputs:
		assert.Zero(t, result)
	case <-time.After(time.Second):
		t.Error("timeout after 1 second")
	}
}
