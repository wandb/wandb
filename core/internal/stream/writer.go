package stream

import (
	"fmt"
	"os"

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
	settings *settings.Settings        // the run's settings
	logger   *observability.CoreLogger // logger for debugging

	// fwdChan is a channel to which to pass work after saving it.
	fwdChan chan runwork.Work

	// store manages the underlying file.
	store *Store

	// recordNum the number of records we've attempted to save.
	recordNum int64
}

// New returns a new Writer.
func (f *WriterFactory) New(fwdChan chan runwork.Work) *Writer {
	return &Writer{
		logger:   f.Logger,
		settings: f.Settings,
		fwdChan:  fwdChan,
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

// Do processes all records on the input channel.
func (w *Writer) Do(allWork <-chan runwork.Work) {
	defer w.logger.Reraise()
	w.logger.Info("writer: started", "stream_id", w.settings.GetRunID())

	w.startStore()

	for work := range allWork {
		w.logger.Debug(
			"writer: got work",
			"work", work,
			"stream_id", w.settings.GetRunID(),
		)

		record := work.ToRecord()
		if !w.isLocal(record) {
			w.setNumber(record)
			w.tryWrite(record)
		}

		if w.settings.IsOffline() && !work.BypassOfflineMode() {
			continue
		}

		w.fwdChan <- work
	}

	if err := w.store.Close(); err != nil {
		w.logger.CaptureError(
			fmt.Errorf("writer: failed closing store: %v", err))
	}

	close(w.fwdChan)
}

// isLocal returns true if the record should not be written to disk.
//
// Requests are never written to disk, and some records can be explicitly marked
// "local" as well.
func (w *Writer) isLocal(record *spb.Record) bool {
	return record.GetRequest() != nil || record.GetControl().GetLocal()
}

// setNumber sets the record's number and increments the current number.
func (w *Writer) setNumber(record *spb.Record) {
	w.recordNum += 1
	record.Num = w.recordNum
}

// tryWrite attempts to save the record to the transaction log.
//
// Errors are captured and logged.
func (w *Writer) tryWrite(record *spb.Record) {
	if err := w.store.Write(record); err != nil {
		w.logger.CaptureError(
			fmt.Errorf("writer: failed to write record: %v", err))
	}
}
