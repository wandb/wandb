package main

/*
typedef const char cchar_t;
*/
import "C"

import (
	"unsafe"

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

//export wandbcoreLogCommit
func wandbcoreLogCommit(num int) {
	run := wandbRuns.Get(num)
	run.LogPartialCommit()
}

//export wandbcoreLogScaler
func wandbcoreLogScaler(num int, log_key *C.char, log_value C.float) {
	run := wandbRuns.Get(num)
	run.Log(map[string]interface{}{
		C.GoString(log_key): float64(log_value),
	})
}

//export wandbcoreLogInts
func wandbcoreLogInts(num int, flags C.uchar, cLength C.int, cKeys **C.cchar_t, cInts *C.int) {
	run := wandbRuns.Get(num)
	keys := unsafe.Slice(cKeys, cLength)
	ints := unsafe.Slice(cInts, cLength)
	logs := make(map[string]interface{})
	for i := range keys {
		logs[C.GoString(keys[i])] = int(ints[i])
	}
	run.LogPartial(logs, (flags != 0))
}

//export wandbcoreLogDoubles
func wandbcoreLogDoubles(num int, flags C.uchar, cLength C.int, cKeys **C.cchar_t, cDoubles *C.double) {
	run := wandbRuns.Get(num)
	keys := unsafe.Slice(cKeys, cLength)
	doubles := unsafe.Slice(cDoubles, cLength)
	logs := make(map[string]interface{})
	for i := range keys {
		logs[C.GoString(keys[i])] = float64(doubles[i])
	}
	run.LogPartial(logs, (flags != 0))
}

//export wandbcoreFinish
func wandbcoreFinish(num int) {
	run := wandbRuns.Get(num)
	run.Finish()
	wandbRuns.Remove(num)
}

//export wandbcoreTeardown
func wandbcoreTeardown() {
	wandbSession.Close()
	wandbSession = nil
}

func main() {
}
