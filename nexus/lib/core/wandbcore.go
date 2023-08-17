package main

import "C"

import (
	"github.com/wandb/wandb/nexus/pkg/gowandb"
	"github.com/wandb/wandb/nexus/pkg/gowandb/opts/session"
)

// globals to keep track of the wandb session and any runs
var wandbSession *gowandb.Session
var wandbRuns *RunKeeper

//export wandbcore_setup
func wandbcore_setup() {
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

//export wandbcore_init
func wandbcore_init() int {
	wandbcore_setup()

	run, err := wandbSession.NewRun()
	if err != nil {
		panic(err)
	}
	num := wandbRuns.Add(run)
	return num
}

//export wandbcore_log_scaler
func wandbcore_log_scaler(num int, log_key *C.char, log_value C.float) {
	run := wandbRuns.Get(num)
	run.Log(map[string]float64{
		C.GoString(log_key): float64(log_value),
	})
}

//export wandbcore_finish
func wandbcore_finish(num int) {
	run := wandbRuns.Get(num)
	run.Finish()
}

//export wandbcore_teardown
func wandbcore_teardown() {
	wandbSession.Close()
	wandbSession = nil
}

func main() {
}
