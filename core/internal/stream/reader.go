package stream

import (
	"fmt"
	"io"
	"os"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/proto"
)

type ReaderParams struct {
	Logger   *observability.CoreLogger
	Settings *settings.Settings
	RunWork  runwork.RunWork
}

type Reader struct {
	settings *settings.Settings
	logger   *observability.CoreLogger
	store    *Store
	runWork  runwork.RunWork
}

func NewReader(params ReaderParams) *Reader {
	return &Reader{
		settings: params.Settings,
		logger:   params.Logger,
		runWork:  params.RunWork,
	}
}

func (r *Reader) Do() {
	defer r.logger.Reraise()
	r.logger.Info("reader: Do: started", "stream_id", r.settings.GetRunID())

	r.store = NewStore(r.settings.GetTransactionLogPath())
	err := r.store.Open(os.O_RDONLY)
	if err != nil {
		err = fmt.Errorf("reader: Do: error opening store: %v", err)
		r.logger.CaptureError(err)
		return
	}

	for {
		record, err := r.store.Read()
		if err == io.EOF {
			return
		}
		if err != nil {
			err = fmt.Errorf("reader: Do: error reading record: %v", err)
			r.logger.CaptureError(err)
			return
		}
		switch record.RecordType.(type) {
		case *spb.Record_Run:
			// if the run id is not set, we use the run id from the record
			if r.settings.GetRunID() == "" {
				r.settings.UpdateRunID(record.GetRun().GetRunId())
			}
			clonedRecord := proto.Clone(record).(*spb.Record)
			// we pass overwrite values through the settings
			// if the values are empty, we use the values from the
			// original record
			proto.Merge(clonedRecord.GetRun(), &spb.RunRecord{
				RunId:   r.settings.GetRunID(),
				Entity:  r.settings.GetEntity(),
				Project: r.settings.GetProject(),
			})
			r.runWork.AddWork(runwork.WorkFromRecord(clonedRecord))
			// need to send a run start request to the sender
			// so it can start the run
			record := &spb.Record{
				RecordType: &spb.Record_Request{
					Request: &spb.Request{
						RequestType: &spb.Request_RunStart{
							RunStart: &spb.RunStartRequest{
								Run: clonedRecord.GetRun(),
							},
						},
					},
				},
			}
			r.runWork.AddWork(runwork.WorkFromRecord(record))
		default:
			r.runWork.AddWork(runwork.WorkFromRecord(record))
		}
	}
}
