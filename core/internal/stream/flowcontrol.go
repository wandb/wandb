package stream

import (
	"errors"
	"fmt"
	"os"

	"github.com/google/wire"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runwork"
)

var flowControlProviders = wire.NewSet(
	wire.Struct(new(FlowControlFactory), "*"),
)

type FlowControlFactory struct {
	Logger *observability.CoreLogger
}

// FlowControl is an infinite-buffered channel for Work.
//
// When blocked, Work that has been saved to disk is discarded and read from
// disk later.
type FlowControl struct {
	out    chan runwork.Work
	buffer *FlowControlBuffer

	transactionLogPath string

	flushWriter  func()
	logger       *observability.CoreLogger
	recordParser RecordParser
}

func (f *FlowControlFactory) New(
	transactionLogPath string,
	flushWriter func(),
	recordParser RecordParser,
) *FlowControl {
	return &FlowControl{
		out: make(chan runwork.Work),
		buffer: NewFlowControlBuffer(FlowControlParams{
			InMemorySize: 32,   // Max records before off-loading.
			Limit:        1024, // Max unsaved records before blocking.
		}),

		transactionLogPath: transactionLogPath,

		flushWriter:  flushWriter,
		logger:       f.Logger,
		recordParser: recordParser,
	}
}

// Do forwards all given work to the output channel, discarding it and
// reading it from the transaction log if the output channel is full.
//
// Closes the output channel after completing.
func (fc *FlowControl) Do(savedWork <-chan runwork.MaybeSavedWork) {
	go func() {
		defer fc.logger.Reraise()

		for work := range savedWork {
			fc.buffer.Add(work)
		}

		fc.buffer.Close()
	}()

	fc.loopFlushBuffer()
}

// Chan returns the output channel.
func (fc *FlowControl) Chan() <-chan runwork.Work {
	return fc.out
}

// loopFlushBuffer pushes buffered or off-loaded work to the output.
func (fc *FlowControl) loopFlushBuffer() {
	defer close(fc.out)

	for {
		item := fc.buffer.Get()
		if item == nil {
			return
		}

		switch x := item.(type) {
		case *FlowControlBufferSavedChunk:
			fc.readSavedChunk(x)
		case *FlowControlBufferWork:
			fc.out <- x.Work
		default:
			panic(fmt.Errorf("stream: FlowControl wrong type: %T", x))
		}
	}
}

// readSavedChunk forwards data from the transaction log.
//
// On any error, the rest of the chunk is skipped. This way, we still do
// a best-effort job of processing the user's run, and later they can hopefully
// sync.
func (fc *FlowControl) readSavedChunk(chunk *FlowControlBufferSavedChunk) {
	fc.flushWriter()

	store := NewStore(fc.transactionLogPath)
	if err := store.Open(os.O_RDONLY); err != nil {
		fc.logger.CaptureError(
			fmt.Errorf("stream: FlowControl failed to open store: %v", err),
			"skippedChunk", chunk,
		)
		return
	}
	defer store.Close() //nolint:errcheck // we only read, not write

	err := store.SeekRecord(chunk.InitialOffset)
	if err != nil {
		fc.logger.CaptureError(
			fmt.Errorf("stream: FlowControl failed to seek: %v", err),
			"skippedChunk", chunk,
		)
		return
	}

	for idx := int64(0); idx < chunk.Count; idx++ {
		record, err := store.Read()

		switch {
		case err != nil:
			// NOTE: EOF is unexpected: we expect the entire chunk to be saved.
			fc.logger.CaptureError(
				fmt.Errorf("stream: FlowControl failed reading: %v", err),
				"skippedChunk", chunk,
				"successfulCount", idx,
			)
			return

		case record.Num != chunk.InitialNumber+idx:
			fc.logger.CaptureError(
				errors.New("stream: FlowControl: unexpected record number"),
				"skippedChunk", chunk,
				"successfulCount", idx,
				"recordNum", record.Num,
				"expectedNum", chunk.InitialNumber+idx,
			)
			return

		default:
			fc.out <- fc.recordParser.Parse(record)
		}
	}
}
