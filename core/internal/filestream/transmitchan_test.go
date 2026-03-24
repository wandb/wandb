package filestream_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/filestream"
)

// nonEmptyRequest makes a non-empty FileStream JSON request for testing.
func nonEmptyRequest() *filestream.FileStreamRequestJSON {
	exitCode := int32(123)
	return &filestream.FileStreamRequestJSON{
		ExitCode: &exitCode,
	}
}

func TestTransmitChan(t *testing.T) {
	ch := filestream.NewTransmitChan()
	requestIn := nonEmptyRequest()

	go ch.Push(requestIn)
	requestOut, ok := ch.NextRequest(make(<-chan time.Time))

	assert.True(t, ok)
	assert.Equal(t, requestIn, requestOut)
}

func TestTransmitChan_Heartbeat(t *testing.T) {
	ch := filestream.NewTransmitChan()
	heartbeatCh := make(chan time.Time, 1)
	heartbeatCh <- time.Now()

	requestOut, ok := ch.NextRequest(heartbeatCh)

	assert.True(t, ok)
	assert.Equal(t, &filestream.FileStreamRequestJSON{}, requestOut)
}

func TestTransmitChan_PreparePush_ReturnsNonBlockingChannel(t *testing.T) {
	ch := filestream.NewTransmitChan()
	defer ch.Close()

	// Read in a loop until the end of the test.
	go func() {
		for {
			_, ok := ch.NextRequest(make(<-chan time.Time))
			if !ok {
				break
			}
		}
	}()

	// Test several times to cover different types of race conditions.
	for range 100 {
		pushChan := <-ch.PreparePush()

		select {
		case pushChan <- nonEmptyRequest():
		default:
			t.Fatal("pushChan blocked")
		}
	}
}

func TestTransmitChan_IgnoreFutureRequests(t *testing.T) {
	ch := filestream.NewTransmitChan()
	defer ch.Close()

	ch.IgnoreFutureRequests()

	for range 100 {
		select {
		case pushChan := <-ch.PreparePush():
			pushChan <- nonEmptyRequest()
		case <-time.After(time.Second):
			t.Fatal("preparePush blocked")
		}
	}
}
