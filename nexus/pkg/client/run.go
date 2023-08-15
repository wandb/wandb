package client

import (
	"context"
	"log/slog"
	"os"
	"strconv"
	"sync"

	"github.com/wandb/wandb/nexus/pkg/service"
)

type Settings map[string]interface{}

type Run struct {
	// ctx is the context for the run
	ctx      context.Context
	settings *service.Settings
	conn     *Connection
	wg       sync.WaitGroup
}

// NewRun creates a new run with the given settings and responders.
func NewRun(ctx context.Context, settings *service.Settings, conn *Connection) *Run {
	run := &Run{
		ctx:      ctx,
		settings: settings,
		conn:     conn,
		wg:       sync.WaitGroup{},
	}
	return run
}

func (r *Run) Setup() {
	err := os.MkdirAll(r.settings.GetLogDir().GetValue(), os.ModePerm)
	if err != nil {
		slog.Error("error creating log dir", "err", err)
	}
	err = os.MkdirAll(r.settings.GetFilesDir().GetValue(), os.ModePerm)
	if err != nil {
		slog.Error("error creating files dir", "err", err)
	}
	r.wg.Add(1)
	go func() {
		r.conn.Recv()
		r.wg.Done()
	}()
}

func (r *Run) Init() {
	serverRecord := service.ServerRequest{
		ServerRequestType: &service.ServerRequest_InformInit{InformInit: &service.ServerInformInitRequest{
			Settings: r.settings,
			XInfo:    &service.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
		}},
	}
	err := r.conn.Send(&serverRecord)
	if err != nil {
		return
	}

	runRecord := service.Record_Run{Run: &service.RunRecord{
		RunId: r.settings.GetRunId().GetValue(),
		//Config: &service.ConfigRecord{},
		XInfo: &service.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
	}}
	record := service.Record{
		RecordType: &runRecord,
		XInfo:      &service.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
	}
	serverRecord = service.ServerRequest{
		ServerRequestType: &service.ServerRequest_RecordCommunicate{RecordCommunicate: &record},
	}

	handle := r.conn.Mbox.Deliver(&record)
	err = r.conn.Send(&serverRecord)
	if err != nil {
		return
	}
	_ = handle.wait()
}

func (r *Run) Start() {
	serverRecord := service.ServerRequest{
		ServerRequestType: &service.ServerRequest_InformStart{InformStart: &service.ServerInformStartRequest{
			Settings: r.settings,
			XInfo:    &service.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
		}},
	}
	err := r.conn.Send(&serverRecord)
	if err != nil {
		return
	}

	request := service.Request{RequestType: &service.Request_RunStart{
		RunStart: &service.RunStartRequest{Run: &service.RunRecord{
			RunId: r.settings.GetRunId().GetValue(),
		}}}}
	record := service.Record{
		RecordType: &service.Record_Request{Request: &request},
		Control:    &service.Control{Local: true},
		XInfo:      &service.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
	}

	serverRecord = service.ServerRequest{
		ServerRequestType: &service.ServerRequest_RecordCommunicate{RecordCommunicate: &record},
	}

	handle := r.conn.Mbox.Deliver(&record)
	err = r.conn.Send(&serverRecord)
	if err != nil {
		return
	}
	handle.wait()
}

func (r *Run) Log(data map[string]float64) {
	history := service.PartialHistoryRequest{}
	for key, value := range data {
		strValue := strconv.FormatFloat(value, 'f', -1, 64)
		history.Item = append(history.Item, &service.HistoryItem{
			Key:       key,
			ValueJson: strValue,
		})
	}
	request := service.Request{
		RequestType: &service.Request_PartialHistory{PartialHistory: &history},
	}
	record := service.Record{
		RecordType: &service.Record_Request{Request: &request},
		Control:    &service.Control{Local: true},
		XInfo:      &service.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
	}

	serverRecord := service.ServerRequest{
		ServerRequestType: &service.ServerRequest_RecordPublish{RecordPublish: &record},
	}

	err := r.conn.Send(&serverRecord)
	if err != nil {
		return
	}
}

func (r *Run) Finish() {
	record := service.Record{
		RecordType: &service.Record_Exit{Exit: &service.RunExitRecord{ExitCode: 0, XInfo: &service.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()}}},
		XInfo:      &service.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
	}
	serverRecord := service.ServerRequest{
		ServerRequestType: &service.ServerRequest_RecordCommunicate{RecordCommunicate: &record},
	}
	handle := r.conn.Mbox.Deliver(&record)
	err := r.conn.Send(&serverRecord)
	if err != nil {
		return
	}
	handle.wait()

	serverRecord = service.ServerRequest{
		ServerRequestType: &service.ServerRequest_InformFinish{InformFinish: &service.ServerInformFinishRequest{
			XInfo: &service.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
		}},
	}
	err = r.conn.Send(&serverRecord)
	if err != nil {
		return
	}
	// r.wg.Wait()
}
