package filestream_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	. "github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/waitingtest"
)

func TestTransmitLoop_Sends(t *testing.T) {
	outputs := make(chan *FileStreamRequestJSON)
	heartbeat := waitingtest.NewFakeStopwatch()
	heartbeat.SetDoneForever()
	loop := TransmitLoop{
		HeartbeatStopwatch:     heartbeat,
		LogFatalAndStopWorking: func(err error) {},
		Send: func(
			ftd *FileStreamRequestJSON,
			c chan<- map[string]any,
		) error {
			outputs <- ftd
			return nil
		},
	}
	testInput, _ := NewRequestReader(&FileStreamRequest{Preempting: true}, 999)

	inputs := make(chan *FileStreamRequestReader, 1)
	inputs <- testInput
	close(inputs)
	_ = loop.Start(inputs, FileStreamOffsetMap{})

	select {
	case result := <-outputs:
		assert.True(t, *result.Preempting)
	case <-time.After(time.Second):
		t.Error("timeout after 1 second")
	}
}

func TestTransmitLoop_SendsHeartbeats(t *testing.T) {
	heartbeat := waitingtest.NewFakeStopwatch()
	inputs := make(chan *FileStreamRequestReader)
	defer close(inputs)
	outputs := make(chan *FileStreamRequestJSON)
	loop := TransmitLoop{
		HeartbeatStopwatch:     heartbeat,
		LogFatalAndStopWorking: func(err error) {},
		Send: func(
			ftd *FileStreamRequestJSON,
			c chan<- map[string]any,
		) error {
			outputs <- ftd
			return nil
		},
	}

	loop.Start(inputs, FileStreamOffsetMap{})
	heartbeat.SetDone()

	select {
	case result := <-outputs:
		assert.Zero(t, *result)
	case <-time.After(time.Second):
		t.Error("timeout after 1 second")
	}
}
