package server

import (
	"context"
	"fmt"
	"io"
	"os"
	"strings"

	log "github.com/sirupsen/logrus"

	"github.com/wandb/wandb/nexus/pkg/service"
)

var m map[int]*NexusStream = make(map[int]*NexusStream)

func PrintHeadFoot(run *service.RunRecord, settings *Settings) {
	// fmt.Println("GOT", ns.run)
	colorReset := "\033[0m"
	colorBrightBlue := "\033[1;34m"
	colorBlue := "\033[34m"
	colorYellow := "\033[33m"

	appURL := strings.Replace(settings.BaseURL, "//api.", "//", 1)
	url := fmt.Sprintf("%v/%v/%v/runs/%v", appURL, run.Entity, run.Project, run.RunId)
	fmt.Printf("%vwandb%v: 🚀 View run %v%v%v at: %v%v%v\n", colorBrightBlue, colorReset, colorYellow, run.DisplayName, colorReset, colorBlue, url, colorReset)
}

func ResultCallback(run *service.RunRecord, settings *Settings, result *service.Result) {
	switch result.ResultType.(type) {
	case *service.Result_RunResult:
		// TODO: distinguish between first and subsequent RunResult
		PrintHeadFoot(run, settings)
	case *service.Result_ExitResult:
		PrintHeadFoot(run, settings)
	}
}

func ResultFromServerResponse(serverResponse *service.ServerResponse) *service.Result {
	if x, ok := serverResponse.ServerResponseType.(*service.ServerResponse_ResultCommunicate); ok {
		r := x.ResultCommunicate
		return r
	}
	return nil
}

func FuncRespondServerResponse(num int) func(ctx context.Context, serverResponse *service.ServerResponse) {
	return func(ctx context.Context, serverResponse *service.ServerResponse) {
		// fmt.Println("GOT", num, serverResponse)
		ns := m[num]

		result := ResultFromServerResponse(serverResponse)
		ns.CaptureResult(result)
		ns.Recv <- result
	}
}

func InitLogging() {
	logFile, err := os.OpenFile("/tmp/logs.txt", os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0666)
	if err != nil {
		log.Fatal(err)
	}

	logToConsole := false
	if logToConsole {
		mw := io.MultiWriter(os.Stderr, logFile)
		log.SetOutput(mw)
	} else {
		log.SetOutput(logFile)
	}

	log.SetFormatter(&log.JSONFormatter{})
	log.SetLevel(log.DebugLevel)
}

func LibStart() int {
	InitLogging()

	base_url := os.Getenv("WANDB_BASE_URL")
	if base_url == "" {
		base_url = "https://api.wandb.ai"
	}
	api_key := os.Getenv("WANDB_API_KEY")
	if api_key == "" {
		panic("set api key WANDB_API_KEY")
	}
	run_id := os.Getenv("WANDB_RUN_ID")
	if run_id == "" {
		run_id = ShortID(8)
	}

	settings := &Settings{
		BaseURL:  base_url,
		ApiKey:   api_key,
		SyncFile: "something.wandb",
		Offline:  false}

	num := LibStartSettings(settings, run_id)
	return num
}

func LibStartSettings(settings *Settings, run_id string) int {
	runRecord := service.RunRecord{RunId: run_id}
	r := service.Record{
		RecordType: &service.Record_Run{Run: &runRecord},
	}

	num := 42
	s := NewStream(FuncRespondServerResponse(num), settings)

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
	// s.ProcessRecord(&r)

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

func LibLogScaler(n int, log_key string, log_value float64) {
	ns := m[n]
	// fmt.Println("GOT", n, log_key, log_value)
	value_json := fmt.Sprintf("%v", log_value)
	historyRequest := service.PartialHistoryRequest{
		Item: []*service.HistoryItem{
			{
				Key:       log_key,
				ValueJson: value_json,
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
