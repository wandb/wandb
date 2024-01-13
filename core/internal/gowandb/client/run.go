package gowandb

import (
	"context"
	"log/slog"
	"os"
	"sync"

	"github.com/segmentio/encoding/json"

	"github.com/wandb/wandb/core/internal/gowandb/client/opts/runopts"
	"github.com/wandb/wandb/core/internal/gowandb/client/runconfig"
	"github.com/wandb/wandb/core/internal/lib/shared"
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

type Settings map[string]interface{}

type Run struct {
	// ctx is the context for the run
	ctx            context.Context
	settings       *pb.Settings
	config         *runconfig.Config
	conn           *Connection
	wg             sync.WaitGroup
	run            *pb.RunRecord
	params         *runopts.RunParams
	partialHistory History
}

// NewRun creates a new run with the given settings and responders.
func NewRun(ctx context.Context, settings *pb.Settings, conn *Connection, runParams *runopts.RunParams) *Run {
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
	serverRecord := pb.ServerRequest{
		ServerRequestType: &pb.ServerRequest_InformInit{InformInit: &pb.ServerInformInitRequest{
			Settings: r.settings,
			XInfo:    &pb.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
		}},
	}
	err := r.conn.Send(&serverRecord)
	if err != nil {
		return
	}

	config := &pb.ConfigRecord{}
	if r.config == nil {
		r.config = &runconfig.Config{}
	}
	for key, value := range *r.config {
		data, err := json.Marshal(value)
		if err != nil {
			panic(err)
		}
		config.Update = append(config.Update, &pb.ConfigItem{
			Key:       key,
			ValueJson: string(data),
		})
	}
	var DisplayName string
	if r.params.Name != nil {
		DisplayName = *r.params.Name
	}
	runRecord := pb.Record_Run{Run: &pb.RunRecord{
		RunId:       r.settings.GetRunId().GetValue(),
		DisplayName: DisplayName,
		Config:      config,
		Telemetry:   r.params.Telemetry,
		XInfo:       &pb.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
	}}
	if r.params.Project != nil {
		runRecord.Run.Project = *r.params.Project
	}
	record := pb.Record{
		RecordType: &runRecord,
		XInfo:      &pb.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
	}
	serverRecord = pb.ServerRequest{
		ServerRequestType: &pb.ServerRequest_RecordCommunicate{RecordCommunicate: &record},
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
	serverRecord := pb.ServerRequest{
		ServerRequestType: &pb.ServerRequest_InformStart{InformStart: &pb.ServerInformStartRequest{
			Settings: r.settings,
			XInfo:    &pb.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
		}},
	}
	err := r.conn.Send(&serverRecord)
	if err != nil {
		return
	}

	request := pb.Request{RequestType: &pb.Request_RunStart{
		RunStart: &pb.RunStartRequest{Run: &pb.RunRecord{
			RunId: r.settings.GetRunId().GetValue(),
		}}}}
	record := pb.Record{
		RecordType: &pb.Record_Request{Request: &request},
		Control:    &pb.Control{Local: true},
		XInfo:      &pb.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
	}

	serverRecord = pb.ServerRequest{
		ServerRequestType: &pb.ServerRequest_RecordCommunicate{RecordCommunicate: &record},
	}

	handle := r.conn.Mbox.Deliver(&record)
	err = r.conn.Send(&serverRecord)
	if err != nil {
		return
	}
	handle.wait()
}

func (r *Run) logCommit(data map[string]interface{}) {
	history := pb.PartialHistoryRequest{}
	for key, value := range data {
		// strValue := strconv.FormatFloat(value, 'f', -1, 64)
		data, err := json.Marshal(value)
		if err != nil {
			panic(err)
		}
		history.Item = append(history.Item, &pb.HistoryItem{
			Key:       key,
			ValueJson: string(data),
		})
	}
	request := pb.Request{
		RequestType: &pb.Request_PartialHistory{PartialHistory: &history},
	}
	record := pb.Record{
		RecordType: &pb.Record_Request{Request: &request},
		Control:    &pb.Control{Local: true},
		XInfo:      &pb.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
	}

	serverRecord := pb.ServerRequest{
		ServerRequestType: &pb.ServerRequest_RecordPublish{RecordPublish: &record},
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
	record := pb.Record{
		RecordType: &pb.Record_Exit{
			Exit: &pb.RunExitRecord{
				ExitCode: 0, XInfo: &pb.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()}}},
		XInfo: &pb.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
	}
	serverRecord := pb.ServerRequest{
		ServerRequestType: &pb.ServerRequest_RecordCommunicate{RecordCommunicate: &record},
	}
	handle := r.conn.Mbox.Deliver(&record)
	err := r.conn.Send(&serverRecord)
	if err != nil {
		return
	}
	handle.wait()
}

func (r *Run) sendShutdown() {
	record := &pb.Record{
		RecordType: &pb.Record_Request{
			Request: &pb.Request{
				RequestType: &pb.Request_Shutdown{
					Shutdown: &pb.ShutdownRequest{},
				},
			}},
		Control: &pb.Control{AlwaysSend: true, ReqResp: true},
	}
	serverRecord := pb.ServerRequest{
		ServerRequestType: &pb.ServerRequest_RecordCommunicate{RecordCommunicate: record},
	}
	handle := r.conn.Mbox.Deliver(record)
	err := r.conn.Send(&serverRecord)
	if err != nil {
		return
	}
	handle.wait()
}

func (r *Run) sendInformFinish() {
	serverRecord := pb.ServerRequest{
		ServerRequestType: &pb.ServerRequest_InformFinish{InformFinish: &pb.ServerInformFinishRequest{
			XInfo: &pb.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
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
