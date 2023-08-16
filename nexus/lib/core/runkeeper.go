package main

import (
	"github.com/wandb/wandb/nexus/pkg/gowandb"
)

type RunKeeper struct {
	runs map[int]*gowandb.Run
}

func NewRunKeeper() *RunKeeper {
	return &RunKeeper{
		runs: make(map[int]*gowandb.Run),
	}
}

func (k *RunKeeper) Get(num int) *gowandb.Run {
	return k.runs[num]
}

func (k *RunKeeper) Add(run *gowandb.Run) int {
	num := 42
	k.runs[num] = run
	return num
}
