package core

/*
typedef const char cchar_t;
#define WANDBCORE_DATA_CREATE 0
typedef enum {
	LIB_GOLANG, LIB_C, LIB_CPP
} library_t;
*/
import "C"

import (
	"unsafe"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"github.com/wandb/wandb/experimental/go-sdk/pkg/runconfig"
	"github.com/wandb/wandb/experimental/go-sdk/pkg/settings"
	"github.com/wandb/wandb/experimental/go-sdk/pkg/wandb"
)

// globals to keep track of the wandb session and any runs
var session *wandb.Session
var runs *RunKeeper
var wandbData *PartialData

//export wandbcoreSetup
func wandbcoreSetup() {
	if session != nil {
		return
	}
	var err error
	session, err = wandb.Setup(&wandb.SessionParams{CoreBinary: coreBinary})
	if err != nil {
		panic(err)
	}
	runs = NewRunKeeper()
	wandbData = NewPartialData()
}

func getTelemetry(library C.library_t) *spb.TelemetryRecord {
	telemetry := &spb.TelemetryRecord{
		Feature: &spb.Feature{},
	}
	switch library {
	case C.LIB_C:
		telemetry.Feature.LibC = true
	case C.LIB_CPP:
		telemetry.Feature.LibCpp = true
	}
	return telemetry
}

//export wandbcoreInit
func wandbcoreInit(configDataNum int, name *C.cchar_t, runID *C.cchar_t, project *C.cchar_t, _ C.library_t) int {
	wandbcoreSetup()

	config := runconfig.Config(wandbData.Get(configDataNum))
	run, err := session.Init(&wandb.RunParams{
		Config: &config,
		Settings: &settings.Settings{
			RunName:    C.GoString(name),
			RunID:      C.GoString(runID),
			RunProject: C.GoString(project),
		},
		// Telemetry: getTelemetry(library),
	})
	if err != nil {
		panic(err)
	}
	num := runs.Add(run)
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

//export wandbcoreDataAddStrings
func wandbcoreDataAddStrings(num int, cLength C.int, cKeys **C.cchar_t, cStrings **C.cchar_t) int {
	num, data := dataCreateOrGet(num)
	keys := unsafe.Slice(cKeys, cLength)
	strings := unsafe.Slice(cStrings, cLength)
	for i := range keys {
		data[C.GoString(keys[i])] = C.GoString(strings[i])
	}
	return num
}

//export wandbcoreLogData
func wandbcoreLogData(runNum int, dataNum int) {
	run := runs.Get(runNum)
	data := wandbData.Get(dataNum)
	run.Log(data, true)
	wandbData.Remove(dataNum)
}

//export wandbcoreFinish
func wandbcoreFinish(num int) {
	run := runs.Get(num)
	run.Finish()
	runs.Remove(num)
}

//export wandbcoreTeardown
func wandbcoreTeardown() {
	session.Close()
	session = nil
}

func main() {
}
