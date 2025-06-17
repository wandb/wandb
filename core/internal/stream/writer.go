package stream

import (
	"fmt"
	"os"
	"sync"

	"github.com/google/wire"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

var writerProviders = wire.NewSet(
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

	// storeMu is a mutex for write operations to the store.
	storeMu sync.Mutex

	// store manages the underlying file.
	store *Store

	// recordNum the number of records we've attempted to save.
	recordNum int64
}

// New returns a new Writer.
func (f *WriterFactory) New() *Writer {
	return &Writer{
		logger:   f.Logger,
		settings: f.Settings,
		out:      make(chan runwork.MaybeSavedWork),
	}
}

func (w *Writer) startStore() {
	w.store = NewStore(w.settings.GetTransactionLogPath())
	err := w.store.Open(os.O_WRONLY)
	if err != nil {
		w.logger.CaptureFatalAndPanic(
			fmt.Errorf("writer: error creating store: %v", err))
	}
}

// Chan returns the output channel.
func (w *Writer) Chan() <-chan runwork.MaybeSavedWork {
	return w.out
}

// Do saves all input Work and pushes it to the output channel,
// closing it at the end.
func (w *Writer) Do(allWork <-chan runwork.Work) {
	defer w.logger.Reraise()
	defer close(w.out)
	w.logger.Info("writer: started", "stream_id", w.settings.GetRunID())

	w.startStore()

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

	if err := w.store.Close(); err != nil {
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
	w.storeMu.Lock()
	defer w.storeMu.Unlock()

	if err := w.store.Write(record); err != nil {
		return 0, err
	}

	return w.store.LastRecordOffset()
}

// Flush ensures all Work the Writer has output has been written to disk.
func (w *Writer) Flush() {
	w.storeMu.Lock()
	defer w.storeMu.Unlock()

	if err := w.store.Flush(); err != nil {
		w.logger.CaptureError(fmt.Errorf("writer: failed to flush: %v", err))
	}
}
