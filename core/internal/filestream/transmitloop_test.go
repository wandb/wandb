package filestream_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/waitingtest"
)

func TestTransmitLoop_Sends(t *testing.T) {
	outputs := make(chan *filestream.FileStreamRequest)
	loop := filestream.TransmitLoop{
		HeartbeatStopwatch:     waitingtest.NewFakeStopwatch(),
		LogFatalAndStopWorking: func(err error) {},
		Send: func(
			ftd *filestream.FileStreamRequest,
			c chan<- map[string]any,
		) error {
			outputs <- ftd
			return nil
		},
	}
	boolTrue := true
	testInput := filestream.FileStreamRequest{Preempting: &boolTrue}

	inputs := make(chan *filestream.FileStreamRequest)
	_ = loop.Start(inputs)
	inputs <- &testInput
	close(inputs)

	select {
	case result := <-outputs:
		assert.Equal(t, testInput, *result)
	case <-time.After(time.Second):
		t.Error("timeout after 1 second")
	}
}

func TestTransmitLoop_SendsHeartbeats(t *testing.T) {
	heartbeat := waitingtest.NewFakeStopwatch()
	inputs := make(chan *filestream.FileStreamRequest)
	defer close(inputs)
	outputs := make(chan *filestream.FileStreamRequest)
	loop := filestream.TransmitLoop{
		HeartbeatStopwatch:     heartbeat,
		LogFatalAndStopWorking: func(err error) {},
		Send: func(
			ftd *filestream.FileStreamRequest,
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
		assert.Zero(t, *result)
	case <-time.After(time.Second):
		t.Error("timeout after 1 second")
	}
}
