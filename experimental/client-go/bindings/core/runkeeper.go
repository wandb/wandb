package core

import (
	"sync"

	"github.com/wandb/wandb/experimental/client-go/pkg/gowandb"
)

type RunKeeper struct {
	index int
	runs  map[int]*gowandb.Run
	mutex sync.Mutex
}

func NewRunKeeper() *RunKeeper {
	return &RunKeeper{
		// arbitrary number to start counting from
		index: 42,
		runs:  make(map[int]*gowandb.Run),
	}
}

func (k *RunKeeper) Get(num int) *gowandb.Run {
	return k.runs[num]
}

func (k *RunKeeper) Remove(num int) {
	k.mutex.Lock()
	defer k.mutex.Unlock()
	delete(k.runs, num)
}

func (k *RunKeeper) Add(run *gowandb.Run) int {
	k.mutex.Lock()
	defer k.mutex.Unlock()
	num := k.index
	k.index += 1
	k.runs[num] = run
	return num
}
