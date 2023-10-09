package server

import (
	"context"

	"github.com/wandb/wandb/nexus/pkg/observability"
	"github.com/wandb/wandb/nexus/pkg/service"
)

// Writer is responsible for writing messages to the append-only log.
// It receives messages from the handler, processes them,
// if the message is to be persisted it writes them to the log.
// It also sends the messages to the sender.
type Writer struct {
	// ctx is the context for the writer
	ctx context.Context

	// settings is the settings for the writer
	settings *service.Settings

	// logger is the logger for the writer
	logger *observability.NexusLogger

	// fwdChan is the channel for forwarding messages to the sender
	fwdChan chan *service.Record

	// store is the store for the writer
	store *Store
}

// NewWriter returns a new Writer
func NewWriter(ctx context.Context, settings *service.Settings, logger *observability.NexusLogger) *Writer {

	w := &Writer{
		ctx:      ctx,
		settings: settings,
		logger:   logger,
		fwdChan:  make(chan *service.Record, BufferSize),
	}
	return w
}

// do is the main loop of the writer to process incoming messages
func (w *Writer) do(inChan <-chan *service.Record) {
	defer w.logger.Reraise()
	w.logger.Info("writer: started", "stream_id", w.settings.RunId)

	var err error
	w.store, err = NewStore(w.ctx, w.settings.GetSyncFile().GetValue(), w.logger)
	if err != nil {
		w.logger.CaptureFatalAndPanic("writer: error creating store", err)
	}

	for record := range inChan {
		w.handleRecord(record)
	}
	w.close()
}

// close closes the writer and all its resources
// which includes the store
func (w *Writer) close() {
	w.logger.Info("writer: closed", "stream_id", w.settings.RunId)
	close(w.fwdChan)
	if err := w.store.Close(); err != nil {
		w.logger.CaptureError("writer: error closing store", err)
	}
}

// handleRecord Writing messages to the append-only log,
// and passing them to the sender.
// We ensure that the messages are written to the log
// before they are sent to the server.
func (w *Writer) handleRecord(record *service.Record) {
	w.logger.Debug("write: got a message", "record", record, "stream_id", w.settings.RunId)
	switch record.RecordType.(type) {
	case *service.Record_Request:
		w.sendRecord(record)
	case nil:
		w.logger.Error("nil record type")
	default:
		w.storeRecord(record)
		w.sendRecord(record)
	}
}

// storeRecord stores the record in the append-only log
func (w *Writer) storeRecord(record *service.Record) {
	if record.GetControl().GetLocal() {
		return
	}
	if err := w.store.storeRecord(record); err != nil {
		w.logger.Error("writer: error storing record", "error", err)
	}
}

func (w *Writer) sendRecord(record *service.Record) {
	// TODO: redo it so it only uses control
	if w.settings.GetXOffline().GetValue() && !record.GetControl().GetAlwaysSend() {
		return
	}
	w.fwdChan <- record
}
