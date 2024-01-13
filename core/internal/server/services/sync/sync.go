package servicelib

import (
	"context"
	"fmt"
	"io"
	"sync"

	"github.com/wandb/wandb/core/internal/observability"
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

type SyncService struct {
	ctx        context.Context
	wg         sync.WaitGroup
	logger     *observability.CoreLogger
	senderFunc func(*pb.Record)
	inChan     chan *pb.Record
	// Result of offline sync to pass to the client when syncing is done
	flushCallback func(error)
	exitSeen      bool
	syncErr       error
	overwrite     *pb.SyncOverwrite
	skip          *pb.SyncSkip
}

type SyncServiceOption func(*SyncService)

func NewSyncService(ctx context.Context, opts ...SyncServiceOption) *SyncService {
	sync := &SyncService{
		ctx:    ctx,
		wg:     sync.WaitGroup{},
		inChan: make(chan *pb.Record),
	}
	for _, opt := range opts {
		opt(sync)
	}
	return sync
}

func WithSyncServiceOverwrite(overwrite *pb.SyncOverwrite) SyncServiceOption {
	return func(s *SyncService) {
		s.overwrite = overwrite
	}
}

func WithSyncServiceSkip(skip *pb.SyncSkip) SyncServiceOption {
	return func(s *SyncService) {
		s.skip = skip
	}
}

func WithSyncServiceLogger(logger *observability.CoreLogger) SyncServiceOption {
	return func(s *SyncService) {
		s.logger = logger
	}
}

func WithSyncServiceSenderFunc(senderFunc func(*pb.Record)) SyncServiceOption {
	return func(s *SyncService) {
		s.senderFunc = senderFunc
	}
}

func WithSyncServiceFlushCallback(syncResultCallback func(error)) SyncServiceOption {
	return func(s *SyncService) {
		s.flushCallback = syncResultCallback
	}
}

func (s *SyncService) SyncRecord(record *pb.Record, err error) {
	if err != nil && err != io.EOF {
		s.syncErr = err
	}

	if err != nil && !s.exitSeen {
		record = &pb.Record{
			RecordType: &pb.Record_Exit{
				Exit: &pb.RunExitRecord{
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
		case *pb.Record_Run:
			s.syncRun(record)
		case *pb.Record_OutputRaw:
			s.syncOutputRaw(record)
		case *pb.Record_Exit:
			s.syncExit(record)
		default:
			s.senderFunc(record)
		}
	}
	s.wg.Done()
}

func (s *SyncService) syncRun(record *pb.Record) {
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
	record = &pb.Record{
		RecordType: &pb.Record_Request{
			Request: &pb.Request{
				RequestType: &pb.Request_RunStart{
					RunStart: &pb.RunStartRequest{},
				},
			},
		},
	}
	s.senderFunc(record)
}

func (s *SyncService) syncExit(record *pb.Record) {
	s.exitSeen = true
	s.senderFunc(record)
}

func (s *SyncService) syncOutputRaw(record *pb.Record) {
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
		s.logger.CaptureError("Flush without callback", fmt.Errorf("flushing sync service"))
		return
	}
	s.flushCallback(s.syncErr)

}
