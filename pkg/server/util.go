package server

import (
	"crypto/rand"

	"github.com/wandb/wandb/nexus/pkg/service"
)

type NexusStream struct {
	Send     chan service.Record
	Recv     chan service.Result
	Run      *service.RunRecord
	Settings *Settings
	Callback func(run *service.RunRecord, settings *Settings, result *service.Result)
}

func (ns *NexusStream) SendRecord(r *service.Record) {
	ns.Send <- *r
}

// func ResultCallback(ns *server.NexusStream, result *service.Result) {

func (ns *NexusStream) SetResultCallback(cb func(run *service.RunRecord, settings *Settings, result *service.Result)) {
	ns.Callback = cb
}

func (ns *NexusStream) Start(s *Stream) {
	// read from send channel and call ProcessRecord
	// in a goroutine
	go func() {
		for {
			select {
			case record := <-ns.Send:
				s.ProcessRecord(&record)
			}
		}
	}()
}

func (ns *NexusStream) CaptureResult(result *service.Result) {
	// fmt.Println("GOT CAPTURE", result)

	switch x := result.ResultType.(type) {
	case *service.Result_RunResult:
		if ns.Run == nil {
			ns.Run = x.RunResult.GetRun()
			// ns.printHeader()
			// fmt.Println("GOT RUN from RESULT", ns.run)
		}
	case *service.Result_ExitResult:
		// ns.printFooter()
	}

	if ns.Callback != nil {
		ns.Callback(ns.Run, ns.Settings, result)
	}
}

var chars = "abcdefghijklmnopqrstuvwxyz1234567890"

func ShortID(length int) string {
	ll := len(chars)
	b := make([]byte, length)
	rand.Read(b) // generates len(b) random bytes
	for i := 0; i < length; i++ {
		b[i] = chars[int(b[i])%ll]
	}
	return string(b)
}
