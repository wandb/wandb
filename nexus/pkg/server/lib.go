package server

import (
	"context"
	"fmt"
	"os"
	"strings"

	"golang.org/x/exp/slog"

	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/nexus/pkg/service"
)

var m = make(map[int]*NexusStream)

func PrintHeadFoot(run *service.RunRecord, settings *service.Settings) {
	// fmt.Println("GOT", ns.run)
	colorReset := "\033[0m"
	colorBrightBlue := "\033[1;34m"
	colorBlue := "\033[34m"
	colorYellow := "\033[33m"

	appURL := strings.Replace(settings.GetBaseUrl().GetValue(), "//api.", "//", 1)
	url := fmt.Sprintf("%v/%v/%v/runs/%v", appURL, run.Entity, run.Project, run.RunId)
	fmt.Printf("%vwandb%v: 🚀 View run %v%v%v at: %v%v%v\n", colorBrightBlue, colorReset, colorYellow, run.DisplayName, colorReset, colorBlue, url, colorReset)
}

func writePortFile(portFile string, port int) {
	tempFile := fmt.Sprintf("%s.tmp", portFile)
	f, err := os.Create(tempFile)
	if err != nil {
		LogError(slog.Default(), "fail create", err)
	}
	defer func(f *os.File) {
		_ = f.Close()
	}(f)

	if _, err = f.WriteString(fmt.Sprintf("sock=%d\n", port)); err != nil {
		LogError(slog.Default(), "fail write", err)
	}

	if _, err = f.WriteString("EOF"); err != nil {
		LogError(slog.Default(), "fail write EOF", err)
	}

	if err = f.Sync(); err != nil {
		LogError(slog.Default(), "fail sync", err)
	}

	if err = os.Rename(tempFile, portFile); err != nil {
		LogError(slog.Default(), "fail rename", err)
	}
	slog.Info("wrote port file", "file", portFile, "port", port)
}

func ResultCallback(run *service.RunRecord, settings *service.Settings, result *service.Result) {
	switch result.ResultType.(type) {
	case *service.Result_RunResult:
		// TODO: distinguish between first and subsequent RunResult
		PrintHeadFoot(run, settings)
	case *service.Result_ExitResult:
		PrintHeadFoot(run, settings)
	}
}

func LibStart() int {
	SetupDefaultLogger()

	baseUrl := os.Getenv("WANDB_BASE_URL")
	if baseUrl == "" {
		baseUrl = "https://api.wandb.ai"
	}
	apiKey := os.Getenv("WANDB_API_KEY")
	if apiKey == "" {
		panic("set api key WANDB_API_KEY")
	}
	runId := os.Getenv("WANDB_RUN_ID")
	if runId == "" {
		runId = ShortID(8)
	}

	settings := &service.Settings{BaseUrl: &wrapperspb.StringValue{
		Value: baseUrl}, ApiKey: &wrapperspb.StringValue{Value: apiKey},
		SyncFile: &wrapperspb.StringValue{Value: "something.wandb"},
		XOffline: &wrapperspb.BoolValue{Value: false}}

	num := LibStartSettings(settings, runId)
	return num
}

func LibStartSettings(settings *service.Settings, runId string) int {
	runRecord := service.RunRecord{RunId: runId}
	r := service.Record{
		RecordType: &service.Record_Run{Run: &runRecord},
	}

	num := 42
	s := NewStream(context.Background(), settings, "junk")
	s.Start()

	c := make(chan *service.Record, 1000)
	d := make(chan *service.Result, 1000)
	if m == nil {
		m = make(map[int]*NexusStream)
	}
	ns := &NexusStream{c, d, nil, settings, nil}
	ns.SetResultCallback(ResultCallback)
	m[num] = ns
	ns.Start(s)

	ns.SendRecord(&r)
	// s.Handle(&r)

	// go processStuff()
	return num
}

func LibRecv(num int) *service.Result {
	ns := m[num]
	got := <-ns.Recv
	// fmt.Println("GOT", &got)
	return got
}

func LibRunStart(n int) {
	ns := m[n]
	run := m[n].Run
	// fmt.Println("SEND RUN START", n, run)

	if run == nil {
		panic("run cant be nil")
	}

	runStartRequest := service.RunStartRequest{}
	runStartRequest.Run = run
	req := service.Request{
		RequestType: &service.Request_RunStart{RunStart: &runStartRequest},
	}
	r := service.Record{
		RecordType: &service.Record_Request{Request: &req},
	}
	ns.SendRecord(&r)
}

func LibLogScaler(n int, logKey string, logValue float64) {
	ns := m[n]
	// fmt.Println("GOT", n, logKey, logValue)
	valueJson := fmt.Sprintf("%v", logValue)
	historyRequest := service.PartialHistoryRequest{
		Item: []*service.HistoryItem{
			{
				Key:       logKey,
				ValueJson: valueJson,
			},
		},
	}
	req := service.Request{
		RequestType: &service.Request_PartialHistory{PartialHistory: &historyRequest},
	}
	r := service.Record{
		RecordType: &service.Record_Request{Request: &req},
	}
	ns.SendRecord(&r)
}

func LibFinish(n int) {
	ns := m[n]
	exitRecord := service.RunExitRecord{}
	r := service.Record{
		RecordType: &service.Record_Exit{Exit: &exitRecord},
	}
	ns.SendRecord(&r)
}
