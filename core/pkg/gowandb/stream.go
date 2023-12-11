package gowandb

import (
	"context"
	"encoding/json"
	"log/slog"
	"os"
	"strings"
	"sync"

	"github.com/wandb/wandb/core/internal/shared"
	"github.com/wandb/wandb/core/pkg/gowandb/opts/runopts"
	"github.com/wandb/wandb/core/pkg/gowandb/runconfig"
	"github.com/wandb/wandb/core/pkg/service"
)

type Stream struct {
	ctx      context.Context
	settings *service.Settings
	config   *runconfig.Config
	conn     *Connection
	wg       sync.WaitGroup
	run      *service.RunRecord
	params   *runopts.RunParams
}

func NewStream(ctx context.Context, settings *service.Settings, conn *Connection, runParams *runopts.RunParams) *Stream {
	run := &Stream{
		ctx:      ctx,
		settings: settings,
		conn:     conn,
		wg:       sync.WaitGroup{},
		config:   runParams.Config,
		params:   runParams,
	}
	return run
}

func (r *Stream) setup() {
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

func (r *Stream) init() {
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
	/*
		if r.params.Name != nil {
			DisplayName = *r.params.Name
		}
	*/
	parts := strings.SplitN(*r.params.Path, "/", 3)
	// runId := r.settings.GetRunId().GetValue(),
	runId := parts[2]
	runRecord := service.Record_StreamTable{StreamTable: &service.StreamTableRecord{
		RunId:   runId,
		Entity:  parts[0],
		Project: parts[1],
		Table:   parts[2],
		XInfo:   &service.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
	}}
	/*
		if r.params.Project != nil {
			runRecord.Run.Project = *r.params.Project
		}
	*/
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

func (r *Stream) start() {
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
}

func (r *Stream) Log(data map[string]interface{}) {
	streamData := service.StreamDataRecord{Items: make(map[string]*service.StreamValue)}
	for key, value := range data {
		switch v := value.(type) {
		case int64:
			streamData.Items[key] = &service.StreamValue{
				StreamValueType: &service.StreamValue_Int64Value{Int64Value: v},
			}
		case float64:
			streamData.Items[key] = &service.StreamValue{
				StreamValueType: &service.StreamValue_DoubleValue{DoubleValue: v},
			}
		case string:
			streamData.Items[key] = &service.StreamValue{
				StreamValueType: &service.StreamValue_StringValue{StringValue: v},
			}
		}
	}
	record := service.Record{
		RecordType: &service.Record_StreamData{StreamData: &streamData},
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

func (r *Stream) sendExit() {
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

func (r *Stream) sendShutdown() {
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

func (r *Stream) sendInformFinish() {
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

func (r *Stream) Finish() {
	r.sendExit()
	r.sendShutdown()
	r.sendInformFinish()

	r.conn.Close()
	r.wg.Wait()
	shared.PrintHeadFoot(r.run, r.settings, true)
}
