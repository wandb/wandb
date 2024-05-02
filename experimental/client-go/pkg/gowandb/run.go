package gowandb

import (
	"context"
	"log/slog"
	"os"
	"sync"

	"github.com/segmentio/encoding/json"

	"github.com/wandb/wandb/core/pkg/gowandb/opts/runopts"
	"github.com/wandb/wandb/core/pkg/service"
	"github.com/wandb/wandb/experimental/client-go/gowandb/runconfig"
)

type Settings map[string]interface{}

type Run struct {
	// ctx is the context for the run
	ctx            context.Context
	settings       *service.Settings
	config         *runconfig.Config
	conn           *Connection
	wg             sync.WaitGroup
	run            *service.RunRecord
	params         *runopts.RunParams
	partialHistory History
}

// NewRun creates a new run with the given settings and responders.
func NewRun(ctx context.Context, settings *service.Settings, conn *Connection, runParams *runopts.RunParams) *Run {
	run := &Run{
		ctx:      ctx,
		settings: settings,
		conn:     conn,
		wg:       sync.WaitGroup{},
		config:   runParams.Config,
		params:   runParams,
	}
	run.resetPartialHistory()
	return run
}

func (r *Run) setup() {
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

func (r *Run) init() {
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

	config := &service.ConfigRecord{}
	if r.config == nil {
		r.config = &runconfig.Config{}
	}
	for key, value := range *r.config {
		data, err := json.Marshal(value)
		if err != nil {
			panic(err)
		}
		config.Update = append(config.Update, &service.ConfigItem{
			Key:       key,
			ValueJson: string(data),
		})
	}
	var DisplayName string
	if r.params.Name != nil {
		DisplayName = *r.params.Name
	}
	runRecord := service.Record_Run{Run: &service.RunRecord{
		RunId:       r.settings.GetRunId().GetValue(),
		DisplayName: DisplayName,
		Config:      config,
		Telemetry:   r.params.Telemetry,
		XInfo:       &service.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
	}}
	if r.params.Project != nil {
		runRecord.Run.Project = *r.params.Project
	}
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
	result := handle.wait()
	r.run = result.GetRunResult().GetRun()
	shared.PrintHeadFoot(r.run, r.settings, false)
}

func (r *Run) start() {
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

func (r *Run) logCommit(data map[string]interface{}) {
	history := service.PartialHistoryRequest{}
	for key, value := range data {
		// strValue := strconv.FormatFloat(value, 'f', -1, 64)
		data, err := json.Marshal(value)
		if err != nil {
			panic(err)
		}
		history.Item = append(history.Item, &service.HistoryItem{
			Key:       key,
			ValueJson: string(data),
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

func (r *Run) resetPartialHistory() {
	r.partialHistory = make(map[string]interface{})
}

func (r *Run) LogPartial(data map[string]interface{}, commit bool) {
	for k, v := range data {
		r.partialHistory[k] = v
	}
	if commit {
		r.LogPartialCommit()
	}
}

func (r *Run) LogPartialCommit() {
	r.logCommit(r.partialHistory)
	r.resetPartialHistory()
}

func (r *Run) Log(data map[string]interface{}) {
	r.LogPartial(data, true)
}

func (r *Run) sendExit() {
	record := service.Record{
		RecordType: &service.Record_Exit{
			Exit: &service.RunExitRecord{
				ExitCode: 0, XInfo: &service.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()}}},
		XInfo: &service.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
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
}

func (r *Run) sendShutdown() {
	record := &service.Record{
		RecordType: &service.Record_Request{
			Request: &service.Request{
				RequestType: &service.Request_Shutdown{
					Shutdown: &service.ShutdownRequest{},
				},
			}},
		Control: &service.Control{AlwaysSend: true, ReqResp: true},
	}
	serverRecord := service.ServerRequest{
		ServerRequestType: &service.ServerRequest_RecordCommunicate{RecordCommunicate: record},
	}
	handle := r.conn.Mbox.Deliver(record)
	err := r.conn.Send(&serverRecord)
	if err != nil {
		return
	}
	handle.wait()
}

func (r *Run) sendInformFinish() {
	serverRecord := service.ServerRequest{
		ServerRequestType: &service.ServerRequest_InformFinish{InformFinish: &service.ServerInformFinishRequest{
			XInfo: &service.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
		}},
	}
	err := r.conn.Send(&serverRecord)
	if err != nil {
		return
	}
}

func (r *Run) Finish() {
	r.sendExit()
	r.sendShutdown()
	r.sendInformFinish()

	r.conn.Close()
	r.wg.Wait()
	shared.PrintHeadFoot(r.run, r.settings, true)
}
