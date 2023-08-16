package main

import "C"

import (
	"fmt"

	"context"

	"github.com/wandb/wandb/nexus/internal/launcher"
	"github.com/wandb/wandb/nexus/pkg/client"
)

// global manager, initialized by wandbcore_setup
var globManager *client.Manager
var globRuns *client.RunKeeper

//export wandbcore_setup
func wandbcore_setup() {
	if globManager != nil {
		return
	}
	ctx := context.Background()
	settings := client.NewSettings()

	_, err := launcher.Launch(nexusImage)
	if err != nil {
		panic("error launching")
	}

	port, err := launcher.Getport()
	if err != nil {
		panic("error getting port")
	}
	addr := fmt.Sprintf("127.0.0.1:%d", port)
	globManager = client.NewManager(ctx, settings, addr)
	globRuns = client.NewRunKeeper()
}

//export wandbcore_init
func wandbcore_init() int {
	wandbcore_setup()

	// ctx := context.Background()
	run := globManager.NewRun()
	num := globRuns.Add(run)

	run.Setup()
	run.Init()
	run.Start()

	return num
}

//export wandbcore_log_scaler
func wandbcore_log_scaler(num int, log_key *C.char, log_value C.float) {
	run := globRuns.Get(num)
	run.Log(map[string]float64{
		C.GoString(log_key): float64(log_value),
	})
}

//export wandbcore_finish
func wandbcore_finish(num int) {
	run := globRuns.Get(num)
	run.Finish()
}

//export wandbcore_teardown
func wandbcore_teardown() {
	globManager.Close()
	globManager = nil
}

func main() {
}
