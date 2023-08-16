package main

import (
	"github.com/wandb/wandb/nexus/pkg/client"
)

type RunKeeper struct {
	runs map[int]*client.Run
}

func NewRunKeeper() *RunKeeper {
	return &RunKeeper{
		runs: make(map[int]*client.Run),
	}
}

func (k *RunKeeper) Get(num int) *client.Run {
	return k.runs[num]
}

func (k *RunKeeper) Add(run *client.Run) int {
	num := 42
	k.runs[num] = run
	return num
}
