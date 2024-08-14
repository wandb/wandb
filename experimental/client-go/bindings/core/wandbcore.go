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

	"github.com/wandb/wandb/core/pkg/service"
	"github.com/wandb/wandb/experimental/client-go/internal/gowandb/internal_runopts"
	"github.com/wandb/wandb/experimental/client-go/pkg/gowandb"
	"github.com/wandb/wandb/experimental/client-go/pkg/opts/runopts"
	"github.com/wandb/wandb/experimental/client-go/pkg/opts/sessionopts"
	"github.com/wandb/wandb/experimental/client-go/pkg/runconfig"
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

func getTelemetry(library C.library_t) *service.TelemetryRecord {
	telemetry := &service.TelemetryRecord{
		Feature: &service.Feature{},
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
func wandbcoreInit(configDataNum int, name *C.cchar_t, runID *C.cchar_t, project *C.cchar_t, library C.library_t) int {
	options := []runopts.RunOption{}
	wandbcoreSetup()

	configData := wandbData.Get(configDataNum)
	options = append(options, runopts.WithConfig(runconfig.Config(configData)))
	goName := C.GoString(name)
	if goName != "" {
		options = append(options, runopts.WithName(goName))
	}
	goRunID := C.GoString(runID)
	if goRunID != "" {
		options = append(options, runopts.WithRunID(goRunID))
	}
	goProject := C.GoString(project)
	if goProject != "" {
		options = append(options, runopts.WithProject(goProject))
	}
	telemetry := getTelemetry(library)
	options = append(options, internal_runopts.WithTelemetry(telemetry))

	run, err := wandbSession.NewRun(options...)
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
