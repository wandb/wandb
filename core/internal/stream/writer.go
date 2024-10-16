package stream

import (
	"fmt"
	"os"
	"sync"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runwork"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type WriterParams struct {
	Logger   *observability.CoreLogger
	Settings *spb.Settings
	FwdChan  chan runwork.Work
}

// Writer is responsible for writing messages to the append-only log.
// It receives messages from the handler, processes them,
// if the message is to be persisted it writes them to the log.
// It also sends the messages to the sender.
type Writer struct {
	// settings is the settings for the writer
	settings *spb.Settings

	// logger is the logger for the writer
	logger *observability.CoreLogger

	// fwdChan is a channel of work to pass to the Sender
	fwdChan chan runwork.Work

	// storeChan is the channel for messages to be stored
	storeChan chan *spb.Record

	// store is the store for the writer
	store *Store

	// recordNum is the running count of stored records
	recordNum int64

	// wg is the wait group for the writer
	wg sync.WaitGroup
}

// NewWriter returns a new Writer
func NewWriter(params WriterParams) *Writer {
	w := &Writer{
		wg:       sync.WaitGroup{},
		logger:   params.Logger,
		settings: params.Settings,
		fwdChan:  params.FwdChan,
	}
	return w
}

func (w *Writer) startStore() {
	if w.settings.GetXSync().GetValue() {
		// do not set up store if we are syncing an offline run
		return
	}

	w.storeChan = make(chan *spb.Record, BufferSize*8)

	var err error
	w.store = NewStore(w.settings.GetSyncFile().GetValue())
	err = w.store.Open(os.O_WRONLY)
	if err != nil {
		w.logger.CaptureFatalAndPanic(
			fmt.Errorf("writer: startStore: error creating store: %v", err))
	}

	w.wg.Add(1)
	go func() {
		for record := range w.storeChan {
			if err = w.store.Write(record); err != nil {
				w.logger.CaptureError(
					fmt.Errorf(
						"writer: startStore: error storing record: %v",
						err,
					))
			}
		}

		if err = w.store.Close(); err != nil {
			w.logger.CaptureError(
				fmt.Errorf("writer: startStore: error closing store: %v", err))
		}
		w.wg.Done()
	}()
}

// Do processes all records on the input channel.
func (w *Writer) Do(allWork <-chan runwork.Work) {
	defer w.logger.Reraise()
	w.logger.Info("writer: Do: started", "stream_id", w.settings.RunId)

	w.startStore()

	for work := range allWork {
		w.logger.Debug(
			"write: Do: got work",
			"work", work,
			"stream_id", w.settings.RunId,
		)

		work.Save(w.writeRecord)

		if w.settings.GetXOffline().GetValue() && !work.BypassOfflineMode() {
			continue
		}

		w.fwdChan <- work
	}

	w.Close()
	w.wg.Wait()
}

// Close closes the writer and all its resources
// which includes the store
func (w *Writer) Close() {
	close(w.fwdChan)
	if w.storeChan != nil {
		close(w.storeChan)
	}
	w.logger.Info("writer: Close: closed", "stream_id", w.settings.RunId)
}

// writeRecord Writing messages to the append-only log,
// and passing them to the sender.
// Ensure that the messages are numbered and written to the transaction log
// before network operations could block processing of the record.
func (w *Writer) writeRecord(record *spb.Record) {
	switch record.RecordType.(type) {
	case *spb.Record_Request:
		// Requests are never written to the transaction log.
	case nil:
		w.logger.Error("writer: writeRecord: nil record type")

	default:
		w.applyRecordNumber(record)
		w.storeRecord(record)
	}
}

// applyRecordNumber labels the protobuf with an increasing number to be stored in transaction log
func (w *Writer) applyRecordNumber(record *spb.Record) {
	if record.GetControl().GetLocal() {
		return
	}
	w.recordNum += 1
	record.Num = w.recordNum
}

// storeRecord stores the record in the append-only log
func (w *Writer) storeRecord(record *spb.Record) {
	if record.GetControl().GetLocal() {
		return
	}
	w.storeChan <- record
}
