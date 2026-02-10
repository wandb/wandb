package stream

import (
	"fmt"

	"github.com/google/wire"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runhandle"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/transactionlog"
)

var flowControlProviders = wire.NewSet(
	wire.Struct(new(FlowControlFactory), "*"),
)

type FlowControlFactory struct {
	Logger    *observability.CoreLogger
	RunHandle *runhandle.RunHandle
}

// FlowControl is an infinite-buffered channel for Work.
//
// When blocked, Work that has been saved to disk is discarded and read from
// disk later.
type FlowControl struct {
	out    chan runwork.Work
	buffer *FlowControlBuffer
	reader *transactionlog.Reader

	flushWriter  func() error
	logger       *observability.CoreLogger
	recordParser RecordParser
}

func (f *FlowControlFactory) New(
	reader *transactionlog.Reader,
	flushWriter func() error,
	recordParser RecordParser,
	params FlowControlParams,
) *FlowControl {
	return &FlowControl{
		out:    make(chan runwork.Work),
		buffer: NewFlowControlBuffer(params, f.Logger, f.RunHandle),
		reader: reader,

		flushWriter:  flushWriter,
		logger:       f.Logger,
		recordParser: recordParser,
	}
}

// Do forwards all given work to the output channel, discarding it and
// reading it from the transaction log if the output channel is full.
//
// Closes the output channel and the transaction log reader after completing.
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
	defer fc.reader.Close()

	for {
		item := fc.buffer.Get()
		if item == nil {
			return
		}

		item.Switch(
			func(work runwork.Work) {
				fc.out <- work
			},
			func(chunk *FlowControlBufferSavedChunk) {
				err := fc.readSavedChunk(chunk)

				if err != nil {
					fc.logger.CaptureError(err, "chunk", chunk)
					fc.buffer.StopOffloading()
				}
			},
		)
	}
}

// readSavedChunk forwards data from the transaction log.
//
// Returns an error and skips the chunk if storeBroken is true.
//
// On any error, the rest of the chunk is skipped. This way, we still do
// a best-effort job of processing the user's run, and later they can hopefully
// sync.
func (fc *FlowControl) readSavedChunk(
	chunk *FlowControlBufferSavedChunk,
) error {
	err := fc.flushWriter()
	if err != nil {
		return fmt.Errorf("flowcontrol: failed to flush writer: %v", err)
	}

	err = fc.reader.SeekRecord(chunk.InitialOffset)
	if err != nil {
		return fmt.Errorf("flowcontrol: failed to seek: %v", err)
	}

	for idx := int64(0); idx < chunk.Count; idx++ {
		record, err := fc.reader.Read()

		switch {
		case err != nil:
			// NOTE: EOF is unexpected: we expect the entire chunk to be saved.
			return fmt.Errorf(
				"flowcontrol: failed reading after %d records: %v",
				idx, err)

		case record.Num != chunk.InitialNumber+idx:
			return fmt.Errorf(
				"flowcontrol: record %d in chunk had number %d, not %d",
				idx, record.Num, chunk.InitialNumber+idx)
		}

		fc.out <- fc.recordParser.Parse(record)
	}

	return nil
}
