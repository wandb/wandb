package server

import (
	"context"
	"fmt"
	"io"

	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

type SyncService struct {
	ctx        context.Context
	logger     *observability.CoreLogger
	senderFunc func(*service.Record)
	inChan     chan *service.Record
	// Result of offline sync to pass to the client when syncing is done
	flushCallback func(error)
	exitSeen      bool
	syncErr       error
	overwrite     *service.SyncOverwrite
	skip          *service.SyncSkip
}

type SyncServiceOption func(*SyncService)

func NewSyncService(ctx context.Context, opts ...SyncServiceOption) *SyncService {
	sync := &SyncService{
		ctx:    ctx,
		inChan: make(chan *service.Record),
	}
	for _, opt := range opts {
		opt(sync)
	}
	return sync
}

func WithSyncServiceOverwrite(overwrite *service.SyncOverwrite) SyncServiceOption {
	return func(s *SyncService) {
		s.overwrite = overwrite
	}
}

func WithSyncServiceSkip(skip *service.SyncSkip) SyncServiceOption {
	return func(s *SyncService) {
		s.skip = skip
	}
}

func WithSyncServiceLogger(logger *observability.CoreLogger) SyncServiceOption {
	return func(s *SyncService) {
		s.logger = logger
	}
}

func WithSyncServiceSenderFunc(senderFunc func(*service.Record)) SyncServiceOption {
	return func(s *SyncService) {
		s.senderFunc = senderFunc
	}
}

func WithSyncServiceFlushCallback(syncResultCallback func(error)) SyncServiceOption {
	return func(s *SyncService) {
		s.flushCallback = syncResultCallback
	}
}

func (s *SyncService) SyncRecord(record *service.Record, err error) {
	if err != nil && err != io.EOF {
		s.syncErr = err
	}

	if err != nil && !s.exitSeen {
		record = &service.Record{
			RecordType: &service.Record_Exit{
				Exit: &service.RunExitRecord{
					ExitCode: 1,
				},
			},
		}
		s.inChan <- record
	} else if record != nil {
		s.inChan <- record
	}
}

func (s *SyncService) Start() {
	go s.sync()
}

func (s *SyncService) sync() {
	for record := range s.inChan {
		// TODO: we remove the control from the record because we don't want to try to
		// respond to a non-existing connection when syncing an offline run. if this is
		// is used for something else, we should re-evaluate this.
		// remove the control from the record:
		record.Control = nil
		switch record.RecordType.(type) {
		case *service.Record_Run:
			s.syncRun(record)
		case *service.Record_OutputRaw:
			s.syncOutputRaw(record)
		case *service.Record_Exit:
			s.syncExit(record)
		default:
			s.senderFunc(record)
		}
	}
}

func (s *SyncService) syncRun(record *service.Record) {
	if s.overwrite != nil {
		if s.overwrite.GetEntity() != "" {
			record.GetRun().Entity = s.overwrite.GetEntity()
		}
		if s.overwrite.GetProject() != "" {
			record.GetRun().Project = s.overwrite.GetProject()
		}
		if s.overwrite.GetRunId() != "" {
			record.GetRun().RunId = s.overwrite.GetRunId()
		}
	}
	s.senderFunc(record)
	record = &service.Record{
		RecordType: &service.Record_Request{
			Request: &service.Request{
				RequestType: &service.Request_RunStart{
					RunStart: &service.RunStartRequest{},
				},
			},
		},
	}
	s.senderFunc(record)
}

func (s *SyncService) syncExit(record *service.Record) {
	s.exitSeen = true
	s.senderFunc(record)
}

func (s *SyncService) syncOutputRaw(record *service.Record) {
	if s.skip != nil && s.skip.GetOutputRaw() {
		return
	}
	s.senderFunc(record)
}

func (s *SyncService) Flush() {
	if s == nil {
		return
	}
	close(s.inChan)
	if s.flushCallback == nil {
		s.logger.CaptureError("Flush without callback", fmt.Errorf("flushing sync service"))
		return
	}
	s.flushCallback(s.syncErr)

}
