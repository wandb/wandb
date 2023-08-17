package main

import "C"

import (
	"github.com/wandb/wandb/nexus/pkg/gowandb"
	"github.com/wandb/wandb/nexus/pkg/gowandb/opts/session"
)

// globals to keep track of the wandb session and any runs
var wandbSession *gowandb.Session
var wandbRuns *RunKeeper

//export wandbcoreSetup
func wandbcoreSetup() {
	if wandbSession != nil {
		return
	}
	var err error
	wandbSession, err = gowandb.NewSession(
		session.WithCoreBinary(coreBinary),
	)
	if err != nil {
		panic(err)
	}
	wandbRuns = NewRunKeeper()
}

//export wandbcoreInit
func wandbcoreInit() int {
	wandbcoreSetup()

	run, err := wandbSession.NewRun()
	if err != nil {
		panic(err)
	}
	num := wandbRuns.Add(run)
	return num
}

//export wandbcoreLogScaler
func wandbcoreLogScaler(num int, log_key *C.char, log_value C.float) {
	run := wandbRuns.Get(num)
	run.Log(map[string]float64{
		C.GoString(log_key): float64(log_value),
	})
}

//export wandbcoreFinish
func wandbcoreFinish(num int) {
	run := wandbRuns.Get(num)
	run.Finish()
}

//export wandbcoreTeardown
func wandbcoreTeardown() {
	wandbSession.Close()
	wandbSession = nil
}

func main() {
}
