package stream

import (
	"fmt"
	"sync"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// noopRecordParser turns every record into work that does nothing.
type noopRecordParser struct{}

func (noopRecordParser) Parse(*spb.Record) runwork.WorkImpl {
	return &runworktest.NoopWork{}
}

// newFinishableStream returns a stream that can be finished immediately.
//
// Its work channel is already closed, so the exit record emitted by
// FinishAndClose is rejected right away instead of waiting for a
// record-processing pipeline that isn't running.
func newFinishableStream() *Stream {
	logger := observability.NewNoOpLogger()

	runWork := runwork.New(BufferSize, logger)
	runWork.Close()

	return &Stream{
		runWork:      runWork,
		logger:       logger,
		recordParser: noopRecordParser{},
		settings:     settings.From(&spb.Settings{Silent: wrapperspb.Bool(true)}),
	}
}

func TestFinishAndCloseAllStreamsWhileGettingStream(t *testing.T) {
	mux := NewStreamMux()
	for i := range 16 {
		require.NoError(t,
			mux.AddStream(fmt.Sprintf("run%d", i), newFinishableStream()))
	}

	stopReading := make(chan struct{})
	readers := sync.WaitGroup{}
	for range 4 {
		readers.Go(func() {
			for {
				select {
				case <-stopReading:
					return
				default:
					_, _ = mux.GetStream("run0")
				}
			}
		})
	}

	mux.FinishAndCloseAllStreams(0)
	close(stopReading)
	readers.Wait()

	_, err := mux.GetStream("run0")
	assert.Error(t, err)
}
