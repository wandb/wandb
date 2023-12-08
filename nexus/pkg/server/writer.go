package server

import (
	"context"
	"os"
	"sync"

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
	logger *observability.CoreLogger

	// fwdChan is the channel for forwarding messages to the sender
	fwdChan chan *service.Record

	// storeChan is the channel for messages to be stored
	storeChan chan *service.Record

	// store is the store for the writer
	store *Store

	// recordNum is the running count of stored records
	recordNum int64

	// wg is the wait group for the writer
	wg sync.WaitGroup
}

// NewWriter returns a new Writer
func NewWriter(ctx context.Context, settings *service.Settings, logger *observability.CoreLogger) *Writer {

	w := &Writer{
		ctx:      ctx,
		settings: settings,
		logger:   logger,
		fwdChan:  make(chan *service.Record, BufferSize),
	}
	return w
}

func (w *Writer) startStore() {
	w.storeChan = make(chan *service.Record, BufferSize*8)

	var err error
	w.store = NewStore(w.ctx, w.settings.GetSyncFile().GetValue(), w.logger)
	err = w.store.Open(os.O_WRONLY)
	if err != nil {
		w.logger.CaptureFatalAndPanic("writer: error creating store", err)
	}

	w.wg = sync.WaitGroup{}
	w.wg.Add(1)
	go func() {
		for record := range w.storeChan {
			if err = w.store.Write(record); err != nil {
				w.logger.Error("writer: error storing record", "error", err)
			}
		}

		if err = w.store.Close(); err != nil {
			w.logger.CaptureError("writer: error closing store", err)
		}
		w.wg.Done()
	}()
}

// do is the main loop of the writer to process incoming messages
func (w *Writer) do(inChan <-chan *service.Record) {
	defer w.logger.Reraise()
	w.logger.Info("writer: started", "stream_id", w.settings.RunId)

	w.startStore()

	for record := range inChan {
		w.handleRecord(record)
	}
	w.wg.Wait()
}

// Close closes the writer and all its resources
// which includes the store
func (w *Writer) Close() {
	close(w.fwdChan)
	if w.storeChan != nil {
		close(w.storeChan)
	}
	w.logger.Info("writer: closed", "stream_id", w.settings.RunId)
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
		w.sendRecord(record)
		w.storeRecord(record)
	}
}

// storeRecord stores the record in the append-only log
func (w *Writer) storeRecord(record *service.Record) {
	if record.GetControl().GetLocal() {
		return
	}
	w.recordNum += 1
	record.Num = w.recordNum
	w.storeChan <- record
}

func (w *Writer) sendRecord(record *service.Record) {
	// TODO: redo it so it only uses control
	if w.settings.GetXOffline().GetValue() && !record.GetControl().GetAlwaysSend() {
		return
	}
	w.fwdChan <- record
}
