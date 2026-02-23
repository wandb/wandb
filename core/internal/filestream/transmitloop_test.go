package filestream_test

import (
	"testing"
	"testing/synctest"
	"time"

	"github.com/stretchr/testify/assert"

	. "github.com/wandb/wandb/core/internal/filestream"
)

func TestTransmitLoop_Sends(t *testing.T) {
	outputs := make(chan *FileStreamRequestJSON)
	loop := TransmitLoop{
		HeartbeatPeriod:        time.Hour,
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
	synctest.Test(t, func(t *testing.T) {
		inputs := NewTransmitChan()
		defer inputs.Close()
		outputs := make(chan *FileStreamRequestJSON)
		loop := TransmitLoop{
			HeartbeatPeriod:        5 * time.Minute,
			LogFatalAndStopWorking: func(err error) {},
			Send: func(
				ftd *FileStreamRequestJSON,
				c chan<- map[string]any,
			) error {
				outputs <- ftd
				return nil
			},
		}

		startTime := time.Now()
		loop.Start(inputs)

		// Wait until a heartbeat.
		time.Sleep(5 * time.Minute)
		// Heartbeat timer should reset before Send(). Pretend Send() blocks.
		time.Sleep(3 * time.Minute)

		result1 := <-outputs // First heartbeat (queued after first sleep).
		result1Time := time.Now()

		result2 := <-outputs // Second heartbeat after only 2 more minutes.
		result2Time := time.Now()

		assert.Zero(t, *result1)
		assert.Zero(t, *result2)
		assert.InEpsilon(t, 8*time.Minute, result1Time.Sub(startTime), 0.01)
		assert.InEpsilon(t, 2*time.Minute, result2Time.Sub(result1Time), 0.01)
	})
}
