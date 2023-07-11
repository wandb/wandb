package server

import (
	"context"

	"github.com/wandb/wandb/nexus/pkg/service"
	"golang.org/x/exp/slog"
)

type Writer struct {
	ctx      context.Context
	settings *service.Settings
	inChan   chan *service.Record
	outChan  chan<- *service.Record
	store    *Store
	logger   *slog.Logger
}

func NewWriter(ctx context.Context, settings *service.Settings, logger *slog.Logger) *Writer {

	writer := &Writer{
		ctx:      ctx,
		settings: settings,
		inChan:   make(chan *service.Record),
		store:    NewStore(settings.GetSyncFile().GetValue(), logger),
		logger:   logger,
	}
	return writer
}

func (w *Writer) Deliver(msg *service.Record) {
	w.inChan <- msg
}

func (w *Writer) do() {
	defer func() {
		w.close()
		slog.Debug("writer: closed")
	}()

	slog.Debug("writer: started", "stream_id", w.settings.GetRunId())
	for msg := range w.inChan {
		LogRecord(w.logger, "write: got msg", msg)
		w.writeRecord(msg)
	}
}

func (w *Writer) close() {
	close(w.outChan)
	err := w.store.Close()
	if err != nil {
		return
	}
}

// writeRecord Writing messages to the append-only log,
// and passing them to the sender.
// We ensure that the messages are written to the log
// before they are sent to the server.
func (w *Writer) writeRecord(rec *service.Record) {
	switch rec.RecordType.(type) {
	case *service.Record_Request:
		w.sendRecord(rec)
	case nil:
		slog.Error("nil record type")
	default:
		w.store.storeRecord(rec)
		w.sendRecord(rec)
	}
}

func (w *Writer) sendRecord(rec *service.Record) {
	control := rec.GetControl()
	LogRecord(w.logger, "WRITER: sendRecord", rec)
	if w.settings.GetXOffline().GetValue() && control != nil && !control.AlwaysSend {
		return
	}
	slog.Debug("WRITER: sendRecord: send")
	w.outChan <- rec
}
