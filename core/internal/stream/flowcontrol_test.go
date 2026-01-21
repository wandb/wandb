package stream_test

import (
	"bytes"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"go.uber.org/mock/gomock"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/stream"
	"github.com/wandb/wandb/core/internal/streamtest"
	"github.com/wandb/wandb/core/internal/transactionlog"
	"github.com/wandb/wandb/core/internal/transactionlogtest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type fcTestFixtures struct {
	Input  chan<- runwork.Work // work to feed to the writer
	Output <-chan runwork.Work // work output by flow control

	Logs             *bytes.Buffer
	MockRecordParser *streamtest.MockRecordParser
}

// setup initializes test objects.
//
// Creates and wires up an unbuffered Writer to a FlowControl instance.
// Tests must close the Input channel and consume the Output channel to avoid
// leaking goroutines.
func setup(
	t *testing.T,
	logReader *transactionlog.Reader,
	logWriter *transactionlog.Writer,
	params stream.FlowControlParams,
) fcTestFixtures {
	t.Helper()

	testLogger, logs := observabilitytest.NewRecordingTestLogger(t)

	ctrl := gomock.NewController(t)
	mockRecordParser := streamtest.NewMockRecordParser(ctrl)

	flowControlFactory := &stream.FlowControlFactory{Logger: testLogger}
	writerFactory := &stream.WriterFactory{
		Logger:   testLogger,
		Settings: settings.New(),
	}

	input := make(chan runwork.Work)

	writer := writerFactory.New(logWriter)
	flowControl := flowControlFactory.New(
		logReader,
		writer.Flush,
		mockRecordParser,
		params,
	)

	go writer.Do(input)
	go flowControl.Do(writer.Chan())

	return fcTestFixtures{
		Input:            input,
		Output:           flowControl.Chan(),
		Logs:             logs,
		MockRecordParser: mockRecordParser,
	}
}

func TestDiscardsAndRereadsWork(t *testing.T) {
	r, w := transactionlogtest.ReaderWriter(t)
	x := setup(t, r, w, stream.FlowControlParams{
		InMemorySize: 1,
		Limit:        10,
	})
	expectedWork1 := &runworktest.NoopWork{Value: "1, never offloaded"}
	expectedWork2to5 := &runworktest.NoopWork{Value: "2, 3, 4 or 5"}

	// Even though InMemorySize is 1, we need to push 5 items to use up all
	// additional buffer created by goroutines. The full buffer space in
	// the system is:
	//   - The Writer goroutine (1 item max)
	//   - The FlowControl goroutine that reads from the Writer (1 item max)
	//   - The FlowControlBuffer (1 in-memory, any number offloaded)
	//   - The FlowControl goroutine that generates the Output (1 item max)
	x.Input <- expectedWork1 // never offloaded
	x.Input <- expectedWork2to5
	x.Input <- expectedWork2to5
	x.Input <- expectedWork2to5
	x.Input <- expectedWork2to5
	close(x.Input)

	// The record parser is only used when discarded data is reloaded.
	x.MockRecordParser.EXPECT().Parse(gomock.Any()).
		Return(expectedWork2to5).
		MaxTimes(4).
		MinTimes(1)

	assert.Equal(t, expectedWork1, <-x.Output)

	idx := 0
	for work := range x.Output {
		assert.Equal(t, expectedWork2to5, work,
			"unexpected output at index %d", idx)
	}
}

func TestStopsDiscardingOnStoreError(t *testing.T) {
	// Feeds values into Input until Output emits a given number of times.
	//
	// Closes Input and consumes Output.
	feedInputUntilOutputCount := func(
		t *testing.T,
		x fcTestFixtures,
		nOutputs int,
	) {
		timeout := time.NewTimer(5 * time.Second)
		for nOutputs > 0 {
			select {
			case <-timeout.C:
				t.Fatal("timed out after 5 seconds")
			default:
			}

			select {
			case <-x.Output:
				nOutputs--
				continue
			default:
			}

			select {
			case x.Input <- &runworktest.NoopWork{}:
			case <-x.Output:
				nOutputs--
			}
		}

		close(x.Input)
		for range x.Output {
		}
	}

	t.Run("broken Read", func(t *testing.T) {
		_, w := transactionlogtest.ReaderWriter(t)
		r := transactionlogtest.ErrorReader(t)
		x := setup(t, r, w, stream.FlowControlParams{
			InMemorySize: 0,
			Limit:        1000,
		})

		feedInputUntilOutputCount(t, x, 1)

		assert.Contains(t, x.Logs.String(), "failed reading")
	})

	t.Run("broken SeekRecord", func(t *testing.T) {
		_, w := transactionlogtest.ReaderWriter(t)
		r := transactionlogtest.UnseekableReader(t)
		x := setup(t, r, w, stream.FlowControlParams{
			InMemorySize: 0,
			Limit:        1000,
		})

		feedInputUntilOutputCount(t, x, 1)

		assert.Contains(t, x.Logs.String(), "failed to seek")
	})

	t.Run("invalid record number", func(t *testing.T) {
		_, w := transactionlogtest.ReaderWriter(t)
		r := transactionlogtest.RecordsReader(t, &spb.Record{Num: 123})
		x := setup(t, r, w, stream.FlowControlParams{
			InMemorySize: 0,
			Limit:        1000,
		})

		feedInputUntilOutputCount(t, x, 1)

		assert.Contains(t, x.Logs.String(),
			"record 0 in chunk had number 123, not 1")
	})
}
