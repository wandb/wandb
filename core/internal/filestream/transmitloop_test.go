package filestream_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	. "github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/internal/waitingtest"
)

func TestTransmitLoop_Sends(t *testing.T) {
	outputs := make(chan *FileStreamRequestJSON)
	loop := TransmitLoop{
		HeartbeatStopwatch:     waiting.NewStopwatch(time.Second),
		LogFatalAndStopWorking: func(err error) {},
		Send: func(
			ftd *FileStreamRequestJSON,
			c chan<- map[string]any,
		) error {
			outputs <- ftd
			return nil
		},
	}
	trueValue := true
	inputRequest := &FileStreamRequestJSON{Preempting: &trueValue}

	inputs := NewTransmitChan()
	_ = loop.Start(inputs)
	inputs.Push(inputRequest)
	inputs.Close()

	select {
	case outputRequest := <-outputs:
		assert.Same(t, inputRequest, outputRequest)
	case <-time.After(time.Second):
		t.Error("timeout after 1 second")
	}
}

func TestTransmitLoop_SendsHeartbeats(t *testing.T) {
	heartbeat := waitingtest.NewFakeStopwatch()
	inputs := NewTransmitChan()
	defer inputs.Close()
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

	loop.Start(inputs)
	heartbeat.SetDone()

	select {
	case result := <-outputs:
		assert.Zero(t, *result)
	case <-time.After(time.Second):
		t.Error("timeout after 1 second")
	}
}
