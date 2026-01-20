package stream

import (
	"fmt"
	"sync"

	"github.com/google/wire"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

var WriterProviders = wire.NewSet(
	wire.Struct(new(WriterFactory), "*"),
)

type WriterFactory struct {
	Logger   *observability.CoreLogger
	Settings *settings.Settings
}

// Writer saves work to the transaction log.
//
// The transaction log is primarily used for offline runs. During online runs,
// it is used for data recovery in case there is an issue uploading data.
type Writer struct {
	logger   *observability.CoreLogger // logger for debugging
	settings *settings.Settings        // the run's settings

	// out is the channel to which processed Work is added.
	out chan runwork.MaybeSavedWork

	// writerMu is a mutex for write operations.
	writerMu sync.Mutex

	// writer writes to the underlying file.
	writer *transactionlog.Writer

	// finished is true after we're done writing.
	finished bool

	// recordNum the number of records we've attempted to save.
	recordNum int64
}

// New returns a new Writer.
func (f *WriterFactory) New(writer *transactionlog.Writer) *Writer {
	return &Writer{
		logger:   f.Logger,
		settings: f.Settings,
		out:      make(chan runwork.MaybeSavedWork),
		writer:   writer,
	}
}

// Chan returns the output channel.
func (w *Writer) Chan() <-chan runwork.MaybeSavedWork {
	return w.out
}

// Do saves all input Work and pushes it to the output channel,
// closing it and the transaction log writer at the end.
func (w *Writer) Do(allWork <-chan runwork.Work) {
	defer w.logger.Reraise()
	defer close(w.out)
	w.logger.Info("writer: started", "stream_id", w.settings.GetRunID())

	for work := range allWork {
		w.logger.Debug(
			"writer: got work",
			"work", work,
			"stream_id", w.settings.GetRunID(),
		)

		savedWork := runwork.MaybeSavedWork{Work: work}

		record := work.ToRecord()
		if !w.isLocal(record) {
			recordNum := w.setNumber(record)
			offset, err := w.write(record)

			if err != nil {
				w.logger.CaptureError(
					fmt.Errorf("writer: failed to save record: %v", err))
			} else {
				savedWork.IsSaved = true
				savedWork.SavedOffset = offset
				savedWork.RecordNumber = recordNum
			}
		}

		if w.settings.IsOffline() && !work.BypassOfflineMode() {
			continue
		}

		w.out <- savedWork
	}

	w.writerMu.Lock()
	defer w.writerMu.Unlock()
	w.finished = true

	if err := w.writer.Close(); err != nil {
		w.logger.CaptureError(
			fmt.Errorf("writer: failed closing store: %v", err))
	}
}

// isLocal returns true if the record should not be written to disk.
//
// Requests are never written to disk, and some records can be explicitly marked
// "local" as well.
func (w *Writer) isLocal(record *spb.Record) bool {
	return record.GetRequest() != nil || record.GetControl().GetLocal()
}

// setNumber sets the record's number and increments the current number.
func (w *Writer) setNumber(record *spb.Record) int64 {
	w.recordNum += 1
	record.Num = w.recordNum
	return w.recordNum
}

// write saves the record to the transaction log.
func (w *Writer) write(record *spb.Record) (int64, error) {
	w.writerMu.Lock()
	defer w.writerMu.Unlock()

	if err := w.writer.Write(record); err != nil {
		return 0, err
	}

	return w.writer.LastRecordOffset()
}

// Flush ensures all Work the Writer has output has been written to disk.
func (w *Writer) Flush() error {
	w.writerMu.Lock()
	defer w.writerMu.Unlock()

	if w.finished {
		return nil
	}

	return w.writer.Flush()
}
