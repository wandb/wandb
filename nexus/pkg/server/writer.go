package server

import (
	"context"
	"sync"

	log "github.com/sirupsen/logrus"
	"github.com/wandb/wandb/nexus/pkg/service"
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
		log.WithFields(log.Fields{"record": msg}).Debug("write: got msg")
		w.writeRecord(msg)
	}
	w.close()
	log.Debug("writer: started and closed")
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
		log.Error("nil record type")
	default:
		w.store.storeRecord(rec)
		w.sendRecord(rec)
	}
}

func (w *Writer) sendRecord(rec *service.Record) {
	control := rec.GetControl()
	log.Debug("WRITER: sendRecord", control, rec)
	if w.settings.Offline && control != nil && !control.AlwaysSend {
		return
	}
	log.Debug("WRITER: sendRecord: send")
	w.outChan <- rec
}

// func (w *Writer) Flush() {
// 	log.Debug("WRITER: close")
// 	close(w.inChan)
// }
