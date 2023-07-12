package server

import (
	"context"

	"github.com/wandb/wandb/nexus/pkg/service"
	"golang.org/x/exp/slog"
)

// Writer is responsible for writing messages to the append-only log.
// It receives messages from the handler, processes them,
// if the message is to be persisted it writes them to the log.
// It also sends the messages to the sender.
type Writer struct {
	// ctx is the context for the writer
	ctx context.Context

	// inChan is the channel for incoming messages
	inChan chan *service.Record

	// outChan is the channel for outgoing messages
	outChan chan<- *service.Record

	// store is the store for the writer
	store *Store

	// settings is the settings for the writer
	settings *service.Settings

	// logger is the logger for the writer
	logger *slog.Logger
}

// NewWriter returns a new Writer
func NewWriter(ctx context.Context, settings *service.Settings, logger *slog.Logger) *Writer {

	store, err := NewStore(ctx, settings.GetSyncFile().GetValue(), logger)
	if err != nil {
		logger.Error("writer: error creating store", "error", err, "stream_id", settings.RunId)
		panic(err)
	}

	writer := &Writer{
		ctx:      ctx,
		settings: settings,
		inChan:   make(chan *service.Record),
		store:    store,
		logger:   logger,
	}
	return writer
}

// do is the main loop of the writer to process incoming messages
func (w *Writer) do() {
	slog.Info("writer: started", "stream_id", w.settings.RunId)
	for msg := range w.inChan {
		w.handleRecord(msg)
	}
	w.close()
}

// close closes the writer and all its resources
// which includes the store
func (w *Writer) close() {
	close(w.outChan)
	if err := w.store.Close(); err != nil {
		w.logger.Error("writer: error closing store", "error", err, "stream_id", w.settings.RunId)
		return
	}
	w.logger.Info("writer: closed", "stream_id", w.settings.RunId)
}

// handleRecord Writing messages to the append-only log,
// and passing them to the sender.
// We ensure that the messages are written to the log
// before they are sent to the server.
func (w *Writer) handleRecord(msg *service.Record) {
	w.logger.Debug("write: got a message", "msg", msg, "stream_id", w.settings.RunId)
	switch msg.RecordType.(type) {
	case *service.Record_Request:
		w.sendRecord(msg)
	case nil:
		slog.Error("nil record type")
	default:
		if err := w.store.storeRecord(msg); err != nil {
			w.logger.Error("writer: error storing record", "error", err, "stream_id", w.settings.RunId)
			return
		}
		w.sendRecord(msg)
	}
}

func (w *Writer) sendRecord(rec *service.Record) {
	control := rec.GetControl()
	// TODO: redo it so it only uses control
	if w.settings.GetXOffline().GetValue() && control != nil && !control.AlwaysSend {
		return
	}
	w.outChan <- rec
}
