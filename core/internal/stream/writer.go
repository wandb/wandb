package stream

import (
	"context"
	"fmt"
	"sync"
	"time"

	"github.com/google/wire"

	"github.com/wandb/wandb/core/internal/filestreamstats"
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
	Stats    *filestreamstats.Stats
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

	// recordNum the number of records we've attempted to save.
	recordNum int64

	// exitFlushRequests are requests which require a response
	// after an exit record is received and the transactionlog is flushed.
	exitFlushRequests []*runwork.Request
	exitFlushed       bool
	exitFlushErr      error

	// stats measures the cost of the upload pipeline. It may be nil.
	stats *filestreamstats.Stats
}

// New returns a new Writer.
func (f *WriterFactory) New(writer *transactionlog.Writer) *Writer {
	return &Writer{
		logger:   f.Logger,
		settings: f.Settings,
		out:      make(chan runwork.MaybeSavedWork),
		writer:   writer,
		stats:    f.Stats,
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
	var tick <-chan time.Time
	if interval := w.settings.GetTransactionLogFlushInterval(); interval > 0 {
		ticker := time.NewTicker(interval)
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
	if record.GetRequest().GetWaitForRunExitFlush() != nil {
		if work.Request != nil {
			if w.exitFlushed {
				w.respondExitFlush(work.Request, w.exitFlushErr)
			} else {
				w.exitFlushRequests = append(w.exitFlushRequests, work.Request)
			}
		}

		// do not forward the WaitForRunExitFlushRequest to sender.
		return
	}

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

	if record.GetExit() != nil {
		err := w.Flush()
		if err != nil {
			w.logger.CaptureError(
				"stream",
				fmt.Errorf("writer: failed to flush after exit: %v", err),
			)
		}

		if !w.exitFlushed {
			w.exitFlushed = true
			w.exitFlushErr = err

			for _, request := range w.exitFlushRequests {
				w.respondExitFlush(request, err)
			}

			w.exitFlushRequests = nil
		}
	}

	w.out <- savedWork
}

func (w *Writer) respondExitFlush(request *runwork.Request, err error) {
	if err != nil {
		request.Respond(&spb.ServerResponse{
			ServerResponseType: &spb.ServerResponse_ErrorResponse{
				ErrorResponse: &spb.ServerErrorResponse{Message: err.Error()},
			},
		})
		return
	}

	request.Respond(&spb.ServerResponse{
		ServerResponseType: &spb.ServerResponse_ResultCommunicate{
			ResultCommunicate: &spb.Result{
				ResultType: &spb.Result_Response{
					Response: &spb.Response{
						ResponseType: &spb.Response_WaitForRunExitFlushResponse{
							WaitForRunExitFlushResponse: &spb.WaitForRunExitFlushResponse{},
						},
					},
				},
			},
		},
	})
}

// finish closes the transaction log writer.
func (w *Writer) finish() {
	for _, request := range w.exitFlushRequests {
		request.WillNotRespond()
	}
	w.exitFlushRequests = nil
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

	start := time.Now()
	err := w.writer.Write(record)
	marshalDuration := time.Since(start)
	if err != nil {
		return 0, err
	}

	if record.GetHistory() != nil {
		w.stats.RecordSegment(
			context.Background(),
			filestreamstats.SegmentTxLogMarshal,
			filestreamstats.StreamHistory,
			marshalDuration,
		)
	}

	offset, err := w.writer.LastRecordOffset()
	if err == nil {
		// The offset after the last record is the size of the log so far.
		w.stats.SetTxLogBytes(offset)
	}
	return offset, err
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
