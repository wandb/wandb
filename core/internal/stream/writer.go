package stream

import (
	"fmt"
	"sync"
	"time"

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

const (
	// flushIntervalMin and flushIntervalMax bound how often buffered records
	// are flushed to the transaction log.
	flushIntervalMin = time.Second
	flushIntervalMax = time.Minute

	// flushCostFactor is the flush interval as a multiple of the last flush's
	// latency, keeping the time spent flushing near 1% on a slow filesystem.
	// On a fast one the minimum interval applies.
	flushCostFactor = 100
)

type WriterFactory struct {
	Logger   *observability.CoreLogger
	Settings *settings.Settings
}

// Writer saves work to the transaction log.
//
// The transaction log is primarily used for offline runs. During online runs,
// it is used for data recovery in case there is an issue uploading data.
//
// Buffered records are flushed to the file periodically so that readers of
// the file, such as `wandb leet`, see a running run's progress.
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

	// dirty is true when records were written since the last flush.
	dirty bool

	// flushLatency is how long the last flush took, which stands in for the
	// speed of the filesystem.
	flushLatency time.Duration

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
	defer w.logger.Reraise("stream")
	defer close(w.out)
	w.logger.Info("writer: started", "stream_id", w.settings.GetRunID())

	// A nil channel never fires, which disables the periodic flush.
	var ticker *time.Ticker
	var tick <-chan time.Time
	if !w.settings.IsDisableTransactionLogFlush() {
		ticker = time.NewTicker(flushIntervalMin)
		defer ticker.Stop()
		tick = ticker.C
	}

	for {
		select {
		case work, ok := <-allWork:
			if !ok {
				w.finish()
				return
			}
			w.process(work)

		case <-tick:
			if err := w.Flush(); err != nil {
				w.logger.CaptureError(
					"stream",
					fmt.Errorf("writer: failed to flush: %v", err),
				)
			}
			ticker.Reset(w.flushInterval())
		}
	}
}

// process saves one Work and pushes it to the output channel.
func (w *Writer) process(work runwork.Work) {
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
				"stream",
				fmt.Errorf("writer: failed to save record: %v", err),
			)
		} else {
			savedWork.IsSaved = true
			savedWork.SavedOffset = offset
			savedWork.RecordNumber = recordNum
		}
	}

	if w.settings.IsOffline() && !work.BypassOfflineMode() {
		return
	}

	w.out <- savedWork
}

// finish closes the transaction log writer.
func (w *Writer) finish() {
	w.writerMu.Lock()
	defer w.writerMu.Unlock()
	w.finished = true

	if err := w.writer.Close(); err != nil {
		w.logger.CaptureError(
			"stream",
			fmt.Errorf("writer: failed closing store: %v", err),
		)
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
	w.dirty = true

	return w.writer.LastRecordOffset()
}

// Flush ensures all Work the Writer has output has been written to disk.
func (w *Writer) Flush() error {
	w.writerMu.Lock()
	defer w.writerMu.Unlock()

	if w.finished || !w.dirty {
		return nil
	}

	start := time.Now()
	err := w.writer.Flush()
	w.flushLatency = time.Since(start)
	if err != nil {
		return err
	}

	w.dirty = false
	return nil
}

// flushInterval returns how long to wait before the next periodic flush.
func (w *Writer) flushInterval() time.Duration {
	w.writerMu.Lock()
	defer w.writerMu.Unlock()

	return min(max(w.flushLatency*flushCostFactor, flushIntervalMin), flushIntervalMax)
}
