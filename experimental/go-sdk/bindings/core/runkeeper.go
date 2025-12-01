package core

import (
	"sync"

	"github.com/wandb/wandb/experimental/go-sdk/pkg/wandb"
)

type RunKeeper struct {
	index int
	runs  map[int]*wandb.Run
	mutex sync.Mutex
}

func NewRunKeeper() *RunKeeper {
	return &RunKeeper{
		// arbitrary number to start counting from
		index: 42,
		runs:  make(map[int]*wandb.Run),
	}
}

func (k *RunKeeper) Get(num int) *wandb.Run {
	return k.runs[num]
}

func (k *RunKeeper) Remove(num int) {
	k.mutex.Lock()
	defer k.mutex.Unlock()
	delete(k.runs, num)
}

func (k *RunKeeper) Add(run *wandb.Run) int {
	k.mutex.Lock()
	defer k.mutex.Unlock()
	num := k.index
	k.index += 1
	k.runs[num] = run
	return num
}
