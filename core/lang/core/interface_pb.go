package main

import (
	"C"
        "unsafe"
	"google.golang.org/protobuf/proto"
	"github.com/wandb/wandb/core/pkg/service"
	"github.com/wandb/wandb/core/pkg/gowandb/opts/runopts"
)

//export pbSessionSetup
func pbSessionSetup() {
	wandbcoreSetup()
}

//export pbSessionTeardown
func pbSessionTeardown() {
        // prob dont want this, we could share nexus across "sessions"
	wandbcoreTeardown()
}

//export pbRunStart
func pbRunStart() int {
	options := []runopts.RunOption{}
	wandbcoreSetup()
	run, err := wandbSession.NewRun(options...)
	if err != nil {
		panic(err)
	}
	num := wandbRuns.Add(run)
	return num
}

//export pbRunLog
func pbRunLog(num int, cBuffer *C.char, cLength C.int) {
        data := C.GoBytes(unsafe.Pointer(cBuffer), cLength)
        // Unmarshal protobuf
        msg := &service.HistoryRecord{}
        if err := proto.Unmarshal(data, msg); err != nil {
                return
        }
        // Process data (here simply prepending a string)
	run := wandbRuns.Get(num)

        // TODO: this might need to be internal
	run.LogHistory(msg)
}

//export pbRunFinish
func pbRunFinish(num int) {
	run := wandbRuns.Get(num)
	run.Finish()
	wandbRuns.Remove(num)
}
