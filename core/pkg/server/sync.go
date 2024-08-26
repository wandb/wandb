package server

import (
	"context"
	"errors"
	"io"
	"sync"

	"github.com/wandb/wandb/core/pkg/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type SyncService struct {
	ctx        context.Context
	wg         sync.WaitGroup
	logger     *observability.CoreLogger
	senderFunc func(*spb.Record)
	inChan     chan *spb.Record
	// Result of offline sync to pass to the client when syncing is done
	flushCallback func(error)
	exitSeen      bool
	syncErr       error
	overwrite     *spb.SyncOverwrite
	skip          *spb.SyncSkip
}

type SyncServiceOption func(*SyncService)

func NewSyncService(ctx context.Context, opts ...SyncServiceOption) *SyncService {
	syncService := &SyncService{
		ctx:    ctx,
		wg:     sync.WaitGroup{},
		inChan: make(chan *spb.Record),
	}
	for _, opt := range opts {
		opt(syncService)
	}
	return syncService
}

func WithSyncServiceOverwrite(overwrite *spb.SyncOverwrite) SyncServiceOption {
	return func(s *SyncService) {
		s.overwrite = overwrite
	}
}

func WithSyncServiceSkip(skip *spb.SyncSkip) SyncServiceOption {
	return func(s *SyncService) {
		s.skip = skip
	}
}

func WithSyncServiceLogger(logger *observability.CoreLogger) SyncServiceOption {
	return func(s *SyncService) {
		s.logger = logger
	}
}

func WithSyncServiceSenderFunc(senderFunc func(*spb.Record)) SyncServiceOption {
	return func(s *SyncService) {
		s.senderFunc = senderFunc
	}
}

func WithSyncServiceFlushCallback(syncResultCallback func(error)) SyncServiceOption {
	return func(s *SyncService) {
		s.flushCallback = syncResultCallback
	}
}

func (s *SyncService) SyncRecord(record *spb.Record, err error) {
	if err != nil && err != io.EOF {
		s.syncErr = err
	}

	if err != nil && !s.exitSeen {
		record = &spb.Record{
			RecordType: &spb.Record_Exit{
				Exit: &spb.RunExitRecord{
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
	s.wg.Add(1)
	go s.sync()
}

func (s *SyncService) Close() {
	close(s.inChan)
	s.wg.Wait()
}

func (s *SyncService) sync() {
	for record := range s.inChan {
		// TODO: we remove the control from the record because we don't want to try to
		// respond to a non-existing connection when syncing an offline run. if this is
		// is used for something else, we should re-evaluate this.
		// remove the control from the record:
		record.Control = nil
		switch record.RecordType.(type) {
		case *spb.Record_Run:
			s.syncRun(record)
		case *spb.Record_OutputRaw:
			s.syncOutputRaw(record)
		case *spb.Record_Exit:
			s.syncExit(record)
		default:
			s.senderFunc(record)
		}
	}
	s.wg.Done()
}

func (s *SyncService) syncRun(record *spb.Record) {
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
	record = &spb.Record{
		RecordType: &spb.Record_Request{
			Request: &spb.Request{
				RequestType: &spb.Request_RunStart{
					RunStart: &spb.RunStartRequest{},
				},
			},
		},
	}
	s.senderFunc(record)
}

func (s *SyncService) syncExit(record *spb.Record) {
	s.exitSeen = true
	s.senderFunc(record)
}

func (s *SyncService) syncOutputRaw(record *spb.Record) {
	if s.skip != nil && s.skip.GetOutputRaw() {
		return
	}
	s.senderFunc(record)
}

func (s *SyncService) Flush() {
	if s == nil {
		return
	}
	s.Close()
	if s.flushCallback == nil {
		s.logger.CaptureError(errors.New("flush without callback"))
		return
	}
	s.flushCallback(s.syncErr)

}
