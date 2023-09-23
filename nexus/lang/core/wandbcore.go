package main

/*
typedef const char cchar_t;
#define WANDBCORE_DATA_CREATE 0
*/
import "C"

import (
	"unsafe"

	"github.com/wandb/wandb/nexus/pkg/gowandb"
	"github.com/wandb/wandb/nexus/pkg/gowandb/opts/runopts"
	"github.com/wandb/wandb/nexus/pkg/gowandb/opts/sessionopts"
)

// globals to keep track of the wandb session and any runs
var wandbSession *gowandb.Session
var wandbRuns *RunKeeper
var wandbData *PartialData

//export wandbcoreSetup
func wandbcoreSetup() {
	if wandbSession != nil {
		return
	}
	var err error
	wandbSession, err = gowandb.NewSession(
		sessionopts.WithCoreBinary(coreBinary),
	)
	if err != nil {
		panic(err)
	}
	wandbRuns = NewRunKeeper()
	wandbData = NewPartialData()
}

//export wandbcoreInit
func wandbcoreInit(configDataNum int) int {
	wandbcoreSetup()

	run, err := wandbSession.NewRun(
		runopts.WithConfig(),
	)
	if err != nil {
		panic(err)
	}
	num := wandbRuns.Add(run)
	return num
}

//export wandbcoreDataCreate
func wandbcoreDataCreate() int {
	num := wandbData.Create()
	return num
}

//export wandbcoreDataFree
func wandbcoreDataFree(num int) {
	wandbData.Remove(num)
}

func dataCreateOrGet(num int) (int, MapData) {
	if num == 0 {
		num = wandbData.Create()
	}
	return num, wandbData.Get(num)
}

//export wandbcoreDataAddInts
func wandbcoreDataAddInts(num int, cLength C.int, cKeys **C.cchar_t, cInts *C.int) int {
	num, data := dataCreateOrGet(num)
	keys := unsafe.Slice(cKeys, cLength)
	ints := unsafe.Slice(cInts, cLength)
	for i := range keys {
		data[C.GoString(keys[i])] = int(ints[i])
	}
	return num
}

//export wandbcoreDataAddDoubles
func wandbcoreDataAddDoubles(num int, cLength C.int, cKeys **C.cchar_t, cDoubles *C.double) int {
	num, data := dataCreateOrGet(num)
	keys := unsafe.Slice(cKeys, cLength)
	doubles := unsafe.Slice(cDoubles, cLength)
	for i := range keys {
		data[C.GoString(keys[i])] = float64(doubles[i])
	}
	return num
}

//export wandbcoreLogData
func wandbcoreLogData(runNum int, dataNum int) {
	run := wandbRuns.Get(runNum)
	data := wandbData.Get(dataNum)
	run.Log(data)
	wandbData.Remove(dataNum)
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
