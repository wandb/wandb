package main

import (
	"C"
	"github.com/wandb/wandb/core/pkg/gowandb/opts/runopts"
)

//export pbSessionSetup
func pbSessionSetup() {
	wandbcoreSetup()
}

//export pbSessionTeardown
func pbSessionTeardown() {
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
func pbRunLog() {
}

//export pbRunFinish
func pbRunFinish(num int) {
	run := wandbRuns.Get(num)
	run.Finish()
	wandbRuns.Remove(num)
}
