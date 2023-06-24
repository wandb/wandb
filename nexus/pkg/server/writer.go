package server

import (
	"context"
	"sync"

	"github.com/wandb/wandb/nexus/pkg/service"
	"golang.org/x/exp/slog"
)

type Writer struct {
	settings *Settings
	inChan   chan *service.Record
	outChan  chan<- *service.Record
	store    *Store
}

func NewWriter(ctx context.Context, settings *Settings) *Writer {

	writer := &Writer{
		settings: settings,
		inChan:   make(chan *service.Record),
		store:    NewStore(settings.SyncFile),
	}
	return writer
}

func (w *Writer) Deliver(msg *service.Record) {
	w.inChan <- msg
}

func (w *Writer) start(wg *sync.WaitGroup) {
	defer wg.Done()
	for msg := range w.inChan {
		LogRecord("write: got msg", msg)
		w.writeRecord(msg)
	}
	w.close()
	slog.Debug("writer: started and closed")
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
	LogRecord("WRITER: sendRecord", rec)
	if w.settings.Offline && control != nil && !control.AlwaysSend {
		return
	}
	slog.Debug("WRITER: sendRecord: send")
	w.outChan <- rec
}

// func (w *Writer) Flush() {
// 	log.Debug("WRITER: close")
// 	close(w.inChan)
// }
