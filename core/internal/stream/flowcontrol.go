package stream

import (
	"errors"
	"fmt"
	"io"
	"os"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runwork"
)

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
	recordParser *RecordParser
}

func NewFlowControl(
	transactionLogPath string,
	flushWriter func(),
	logger *observability.CoreLogger,
	recordParser *RecordParser,
) *FlowControl {
	return &FlowControl{
		out: make(chan runwork.Work),
		buffer: NewFlowControlBuffer(FlowControlParams{
			InMemorySize: 32,   // Up to this many records before off-loading.
			Limit:        1024, // Up to this many non-saved records before blocking.
		}),

		transactionLogPath: transactionLogPath,

		flushWriter:  flushWriter,
		logger:       logger,
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
		item := fc.buffer.Pop()
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
	defer store.Close()

	err := store.SeekRecord(chunk.InitialOffset)
	if err != nil {
		fc.logger.CaptureError(
			fmt.Errorf("stream: FlowControl failed to seek: %v", err),
			"skippedChunk", chunk,
		)
		return
	}

	for idx := uint64(0); idx < chunk.Count; idx++ {
		record, err := store.Read()

		switch {
		case errors.Is(err, io.EOF):
			return

		case err != nil:
			fc.logger.CaptureError(
				fmt.Errorf("stream: FlowControl failed reading: %v", err),
				"skippedChunk", chunk,
				"successfulCount", idx,
			)
			return

		case (idx == 0 && record.Num != chunk.InitialNumber) ||
			(idx == chunk.Count-1 && record.Num != chunk.FinalNumber):
			fc.logger.CaptureError(
				errors.New("stream: FlowControl: transaction log may be corrupted"),
				"skippedChunk", chunk,
				"successfulCount", idx,
				"recordNum", record.Num,
			)
			return

		default:
			fc.out <- fc.recordParser.Parse(record)
		}
	}
}
