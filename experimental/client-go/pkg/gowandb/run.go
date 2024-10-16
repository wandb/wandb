package gowandb

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"sync"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"

	"github.com/wandb/wandb/experimental/client-go/pkg/opts/runopts"
	"github.com/wandb/wandb/experimental/client-go/pkg/runconfig"
)

type Settings map[string]interface{}

type Run struct {
	// ctx is the context for the run
	ctx            context.Context
	settings       *spb.Settings
	config         *runconfig.Config
	conn           *Connection
	wg             sync.WaitGroup
	run            *spb.RunRecord
	params         *runopts.RunParams
	partialHistory History
}

// NewRun creates a new run with the given settings and responders.
func NewRun(ctx context.Context, settings *spb.Settings, conn *Connection, runParams *runopts.RunParams) *Run {
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
	serverRecord := spb.ServerRequest{
		ServerRequestType: &spb.ServerRequest_InformInit{InformInit: &spb.ServerInformInitRequest{
			Settings: r.settings,
			XInfo:    &spb.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
		}},
	}
	err := r.conn.Send(&serverRecord)
	if err != nil {
		return
	}

	config := &spb.ConfigRecord{}
	if r.config == nil {
		r.config = &runconfig.Config{}
	}
	for key, value := range *r.config {
		data, err := json.Marshal(value)
		if err != nil {
			panic(err)
		}
		config.Update = append(config.Update, &spb.ConfigItem{
			Key:       key,
			ValueJson: string(data),
		})
	}
	var DisplayName string
	if r.params.Name != nil {
		DisplayName = *r.params.Name
	}
	runRecord := spb.Record_Run{Run: &spb.RunRecord{
		RunId:       r.settings.GetRunId().GetValue(),
		DisplayName: DisplayName,
		Config:      config,
		Telemetry:   r.params.Telemetry,
		XInfo:       &spb.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
	}}
	if r.params.Project != nil {
		runRecord.Run.Project = *r.params.Project
	}
	record := spb.Record{
		RecordType: &runRecord,
		XInfo:      &spb.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
	}
	serverRecord = spb.ServerRequest{
		ServerRequestType: &spb.ServerRequest_RecordCommunicate{RecordCommunicate: &record},
	}

	handle := r.conn.Mbox.Deliver(&record)
	err = r.conn.Send(&serverRecord)
	if err != nil {
		return
	}
	result := handle.wait()
	r.run = result.GetRunResult().GetRun()
	PrintHeadFoot(r.run, r.settings, false)
}

func (r *Run) start() {
	serverRecord := spb.ServerRequest{
		ServerRequestType: &spb.ServerRequest_InformStart{InformStart: &spb.ServerInformStartRequest{
			Settings: r.settings,
			XInfo:    &spb.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
		}},
	}
	err := r.conn.Send(&serverRecord)
	if err != nil {
		return
	}

	request := spb.Request{RequestType: &spb.Request_RunStart{
		RunStart: &spb.RunStartRequest{Run: &spb.RunRecord{
			RunId: r.settings.GetRunId().GetValue(),
		}}}}
	record := spb.Record{
		RecordType: &spb.Record_Request{Request: &request},
		Control:    &spb.Control{Local: true},
		XInfo:      &spb.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
	}

	serverRecord = spb.ServerRequest{
		ServerRequestType: &spb.ServerRequest_RecordCommunicate{RecordCommunicate: &record},
	}

	handle := r.conn.Mbox.Deliver(&record)
	err = r.conn.Send(&serverRecord)
	if err != nil {
		return
	}
	handle.wait()
}

func (r *Run) logCommit(data map[string]interface{}) {
	history := spb.PartialHistoryRequest{}
	for key, value := range data {
		// strValue := strconv.FormatFloat(value, 'f', -1, 64)
		data, err := json.Marshal(value)
		if err != nil {
			panic(err)
		}
		history.Item = append(history.Item, &spb.HistoryItem{
			Key:       key,
			ValueJson: string(data),
		})
	}
	request := spb.Request{
		RequestType: &spb.Request_PartialHistory{PartialHistory: &history},
	}
	record := spb.Record{
		RecordType: &spb.Record_Request{Request: &request},
		Control:    &spb.Control{Local: true},
		XInfo:      &spb.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
	}

	serverRecord := spb.ServerRequest{
		ServerRequestType: &spb.ServerRequest_RecordPublish{RecordPublish: &record},
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
	record := spb.Record{
		RecordType: &spb.Record_Exit{
			Exit: &spb.RunExitRecord{
				ExitCode: 0, XInfo: &spb.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()}}},
		XInfo: &spb.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
	}
	serverRecord := spb.ServerRequest{
		ServerRequestType: &spb.ServerRequest_RecordCommunicate{RecordCommunicate: &record},
	}
	handle := r.conn.Mbox.Deliver(&record)
	err := r.conn.Send(&serverRecord)
	if err != nil {
		return
	}
	handle.wait()
}

func (r *Run) sendShutdown() {
	record := &spb.Record{
		RecordType: &spb.Record_Request{
			Request: &spb.Request{
				RequestType: &spb.Request_Shutdown{
					Shutdown: &spb.ShutdownRequest{},
				},
			}},
		Control: &spb.Control{AlwaysSend: true, ReqResp: true},
	}
	serverRecord := spb.ServerRequest{
		ServerRequestType: &spb.ServerRequest_RecordCommunicate{RecordCommunicate: record},
	}
	handle := r.conn.Mbox.Deliver(record)
	err := r.conn.Send(&serverRecord)
	if err != nil {
		return
	}
	handle.wait()
}

func (r *Run) sendInformFinish() {
	serverRecord := spb.ServerRequest{
		ServerRequestType: &spb.ServerRequest_InformFinish{InformFinish: &spb.ServerInformFinishRequest{
			XInfo: &spb.XRecordInfo{StreamId: r.settings.GetRunId().GetValue()},
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
	PrintHeadFoot(r.run, r.settings, true)
}

// This is used by the go wandb client to print the header and footer of the run
func PrintHeadFoot(run *spb.RunRecord, settings *spb.Settings, footer bool) {
	if run == nil {
		return
	}

	appURL := strings.Replace(settings.GetBaseUrl().GetValue(), "//api.", "//", 1)
	url := fmt.Sprintf("%v/%v/%v/runs/%v", appURL, run.Entity, run.Project, run.RunId)

	fmt.Printf("%v: 🚀 View run %v at: %v\n",
		format("wandb", colorBrightBlue),
		format(run.DisplayName, colorYellow),
		format(url, colorBlue),
	)

	if footer {
		currentDir, err := os.Getwd()
		if err != nil {
			return
		}
		logDir := settings.GetLogDir().GetValue()
		relLogDir, err := filepath.Rel(currentDir, logDir)
		if err != nil {
			return
		}
		fmt.Printf("%v: Find logs at: %v\n",
			format("wandb", colorBrightBlue),
			format(relLogDir, colorBrightMagenta),
		)
	}
}

const (
	resetFormat = "\033[0m"

	colorBrightBlue = "\033[1;34m"

	colorBlue = "\033[34m"

	colorYellow = "\033[33m"

	colorBrightMagenta = "\033[1;35m"
)

func format(str string, color string) string {
	return fmt.Sprintf("%v%v%v", color, str, resetFormat)
}

// This is used by the go wandb client to print the header and footer of the run
func PrintHeadFoot(run *service.RunRecord, settings *service.Settings, footer bool) {
	if run == nil {
		return
	}

	appURL := strings.Replace(settings.GetBaseUrl().GetValue(), "//api.", "//", 1)
	url := fmt.Sprintf("%v/%v/%v/runs/%v", appURL, run.Entity, run.Project, run.RunId)

	fmt.Printf("%v: 🚀 View run %v at: %v\n",
		format("wandb", colorBrightBlue),
		format(run.DisplayName, colorYellow),
		format(url, colorBlue),
	)

	if footer {
		currentDir, err := os.Getwd()
		if err != nil {
			return
		}
		logDir := settings.GetLogDir().GetValue()
		relLogDir, err := filepath.Rel(currentDir, logDir)
		if err != nil {
			return
		}
		fmt.Printf("%v: Find logs at: %v\n",
			format("wandb", colorBrightBlue),
			format(relLogDir, colorBrightMagenta),
		)
	}
}
