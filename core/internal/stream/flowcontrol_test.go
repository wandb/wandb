package stream_test

import (
	"bytes"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/stream"
	"github.com/wandb/wandb/core/internal/streamtest"
	"github.com/wandb/wandb/core/internal/transactionlog"
	"github.com/wandb/wandb/core/internal/transactionlogtest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"go.uber.org/mock/gomock"
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
	feedInputCountOutput := func(x fcTestFixtures, nInput int) int {
		go func() {
			for range nInput {
				x.Input <- &runworktest.NoopWork{}
			}
			close(x.Input)
		}()

		outputCount := 0
		for range x.Output {
			outputCount += 1
		}

		return outputCount
	}

	t.Run("broken Read", func(t *testing.T) {
		_, w := transactionlogtest.ReaderWriter(t)
		r := transactionlogtest.RecordThenErrorReader(t, &spb.Record{Num: 1})
		x := setup(t, r, w, stream.FlowControlParams{
			InMemorySize: 0,
			Limit:        1000,
		})
		x.MockRecordParser.EXPECT().
			Parse(gomock.Any()).
			Return(&runworktest.NoopWork{})

		outputCount := feedInputCountOutput(x, 1000)

		assert.Contains(t, x.Logs.String(), "failed reading")
		assert.Greater(t, outputCount, 1)
	})

	t.Run("broken SeekRecord", func(t *testing.T) {
		_, w := transactionlogtest.ReaderWriter(t)
		r := transactionlogtest.UnseekableReader(t)
		x := setup(t, r, w, stream.FlowControlParams{
			InMemorySize: 0,
			Limit:        1000,
		})

		outputCount := feedInputCountOutput(x, 1000)

		assert.Contains(t, x.Logs.String(), "failed to seek")
		assert.Greater(t, outputCount, 0)
	})

	t.Run("invalid record number", func(t *testing.T) {
		_, w := transactionlogtest.ReaderWriter(t)
		r := transactionlogtest.RecordsReader(t, &spb.Record{Num: 123})
		x := setup(t, r, w, stream.FlowControlParams{
			InMemorySize: 0,
			Limit:        1000,
		})

		outputCount := feedInputCountOutput(x, 1000)

		assert.Contains(t, x.Logs.String(),
			"record 0 in chunk had number 123, not 1")
		assert.Greater(t, outputCount, 0)
	})
}
